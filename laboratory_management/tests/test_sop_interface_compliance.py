from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestSopInterfaceCompliance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "SOP Patient", "lang": "en_US"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "SOP Glucose",
                "code": "SOP-GLU",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "turnaround_hours": 4,
                "list_price": 10.0,
            }
        )
        cls.policy = cls.env["lab.retest.policy"].create(
            {
                "name": "Service Retest Policy",
                "code": "RET-SVC-001",
                "scope": "service",
                "service_ids": [(6, 0, [cls.service.id])],
                "max_retest_count": 1,
                "require_reason": True,
                "cooldown_minutes": 0,
                "escalate_after_failures": 1,
            }
        )
        cls.sop = cls.env["lab.department.sop"].create(
            {
                "name": "Chem SOP",
                "code": "SOP-CHEM-T",
                "department": "chemistry",
                "state": "active",
                "retest_policy_id": cls.policy.id,
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analyze"}),
                    (0, 0, {"sequence": 30, "step_code": "release", "name": "Release"}),
                ],
            }
        )
        cls.service.sop_id = cls.sop
        cls.service.retest_policy_id = cls.policy

        cls.endpoint = cls.env["lab.interface.endpoint"].create(
            {
                "name": "HIS Endpoint",
                "code": "HIS-001",
                "system_type": "his",
                "direction": "bidirectional",
                "protocol": "rest",
                "endpoint_url": "http://localhost/mock",
            }
        )

    def _create_request_and_sample(self):
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_id": self.partner.id,
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "line_type": "service",
                            "service_id": self.service.id,
                            "quantity": 1,
                            "unit_price": 10.0,
                        },
                    )
                ],
            }
        )
        request.action_submit()
        request.action_prepare_quote()
        request.action_approve_quote()
        request.action_create_samples()
        return request, request.sample_ids[:1]

    def test_01_receive_assigns_sop(self):
        _, sample = self._create_request_and_sample()
        sample.action_receive()
        self.assertEqual(sample.sop_id, self.sop)
        self.assertEqual(sample.sop_step_code, "accession")

    def test_02_retest_policy_requires_reason_and_limit(self):
        _, sample = self._create_request_and_sample()
        sample.action_receive()
        sample.action_start()
        line = sample.analysis_ids[:1]
        line.result_value = "8.5"
        line.action_mark_done()

        line.result_note = "Analyzer drift recheck."
        line.action_request_retest()
        with self.assertRaises(UserError):
            line.action_request_retest()

    def test_03_request_submit_creates_interface_order_job(self):
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [(0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1})],
            }
        )
        request.action_submit()
        self.assertGreaterEqual(request.interface_job_count, 1)
        self.assertEqual(request.interface_job_ids[:1].message_type, "order")

    def test_04_report_release_creates_interface_report_job(self):
        _, sample = self._create_request_and_sample()
        sample.action_receive()
        sample.action_start()
        line = sample.analysis_ids[:1]
        line.result_value = "5.1"
        line.action_verify_result()
        sample.write(
            {
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        sample.action_release_report()
        self.assertGreaterEqual(sample.interface_job_count, 1)
        self.assertIn("report", sample.interface_job_ids.mapped("message_type"))

    def test_05_process_interface_jobs(self):
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [(0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1})],
            }
        )
        request.action_submit()
        jobs = request.interface_job_ids
        jobs.action_process()
        self.assertTrue(all(j.state == "done" for j in jobs))

    def test_06_eqa_round_evaluate(self):
        scheme = self.env["lab.eqa.scheme"].create(
            {
                "name": "National Chemistry EQA",
                "code": "EQA-CH-1",
                "provider": "National Lab",
                "department": "chemistry",
            }
        )
        round_rec = self.env["lab.eqa.round"].create(
            {
                "name": "2026-Q1",
                "scheme_id": scheme.id,
                "sample_date": fields.Date.today(),
                "result_ids": [
                    (0, 0, {"service_id": self.service.id, "expected_value": 100, "reported_value": 101}),
                    (0, 0, {"service_id": self.service.id, "expected_value": 100, "reported_value": 500}),
                ],
            }
        )
        round_rec.action_submit()
        round_rec.action_evaluate()
        self.assertEqual(round_rec.state, "evaluated")
        self.assertEqual(round_rec.fail_count, 1)

    def test_07_compliance_snapshot_generate(self):
        _, sample = self._create_request_and_sample()
        sample.action_receive()
        sample.action_start()
        sample.analysis_ids[:1].write({"result_value": "3.2"})
        sample.analysis_ids[:1].action_verify_result()
        sample.write(
            {
                "technical_review_state": "approved",
                "technical_reviewer_id": self.env.user.id,
                "technical_reviewed_at": fields.Datetime.now(),
                "medical_review_state": "approved",
                "medical_reviewer_id": self.env.user.id,
                "medical_reviewed_at": fields.Datetime.now(),
            }
        )
        sample.action_release_report()

        snapshot = self.env["lab.compliance.snapshot"].create(
            {"period_start": fields.Date.today(), "period_end": fields.Date.today()}
        )
        snapshot.action_generate()
        self.assertGreaterEqual(snapshot.total_samples, 1)
        self.assertGreaterEqual(len(snapshot.line_ids), 1)

    def test_08_workbench_counts_include_new_metrics(self):
        wizard = self.env["lab.workbench.wizard"].create({})
        vals = wizard._count_values()
        self.assertIn("submitted_request_count", vals)
        self.assertIn("interface_failed_count", vals)
        self.assertIn("qc_reject_count", vals)

    def test_09_inbound_order_idempotent_by_external_uid(self):
        payload = {
            "patient_name": "Inbound Patient",
            "priority": "routine",
            "sample_type": "blood",
            "lines": [{"service_code": self.service.code, "qty": 1}],
        }
        job1 = self.endpoint.ingest_message("order", payload, external_uid="EXT-001", source_ip="127.0.0.1")
        job2 = self.endpoint.ingest_message("order", payload, external_uid="EXT-001", source_ip="127.0.0.1")
        self.assertEqual(job1.id, job2.id)
        self.assertEqual(job1.state, "done")
        self.assertTrue(job1.request_id)

    def test_10_inbound_result_updates_analysis(self):
        _request, sample = self._create_request_and_sample()
        sample.action_receive()
        sample.action_start()
        payload = {
            "accession": sample.name,
            "results": [{"service_code": self.service.code, "result": "6.8", "note": "from HIS"}],
        }
        job = self.endpoint.ingest_message("result", payload, external_uid="EXT-R-1", source_ip="127.0.0.1")
        self.assertEqual(job.state, "done")
        analysis = sample.analysis_ids.filtered(lambda a: a.service_id == self.service)[:1]
        self.assertEqual(analysis.result_value, "6.8")

    def test_11_dead_letter_and_requeue(self):
        endpoint = self.env["lab.interface.endpoint"].create(
            {
                "name": "Inbound Strict",
                "code": "HIS-STRICT",
                "system_type": "his",
                "direction": "inbound",
                "protocol": "rest",
                "retry_limit": 0,
                "dead_letter_enabled": True,
            }
        )
        bad_payload = {"patient_name": "X", "lines": [{"service_code": "NO-SUCH"}]}
        job = endpoint.ingest_message("order", bad_payload, external_uid="EXT-BAD-1", source_ip="127.0.0.1")
        self.assertEqual(job.state, "dead_letter")
        self.assertTrue(job.dead_letter_reason)
        job.action_requeue()
        self.assertEqual(job.state, "queued")

    def test_12_outbound_mapping_profile_applied(self):
        map_profile = self.env["lab.interface.mapping.profile"].create(
            {
                "name": "Out Map",
                "code": "OUT-MAP-T",
                "protocol": "rest",
                "direction": "outbound",
                "message_type": "order",
                "line_ids": [
                    (0, 0, {"source_path": "request_no", "target_path": "external_order_id"}),
                    (0, 0, {"source_path": "priority", "target_path": "urgency", "transform": "upper"}),
                ],
            }
        )
        self.endpoint.outbound_mapping_profile_id = map_profile
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [(0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1})],
            }
        )
        request.action_submit()
        job = request.interface_job_ids[:1]
        payload = job._build_payload()
        self.assertIn("external_order_id", payload)
        self.assertEqual(payload.get("urgency"), "ROUTINE")

    def test_13_inbound_mapping_profile_applied(self):
        map_profile = self.env["lab.interface.mapping.profile"].create(
            {
                "name": "In Map",
                "code": "IN-MAP-T",
                "protocol": "rest",
                "direction": "inbound",
                "message_type": "order",
                "line_ids": [
                    (0, 0, {"source_path": "ext_patient", "target_path": "patient_name"}),
                    (0, 0, {"source_path": "ext_priority", "target_path": "priority", "transform": "lower"}),
                    (0, 0, {"source_path": "ext_sample", "target_path": "sample_type", "transform": "lower"}),
                    (0, 0, {"source_path": "ext_lines", "target_path": "lines"}),
                ],
            }
        )
        self.endpoint.inbound_mapping_profile_id = map_profile
        payload = {
            "ext_patient": "Mapped Patient",
            "ext_priority": "ROUTINE",
            "ext_sample": "BLOOD",
            "ext_lines": [{"service_code": self.service.code, "qty": 1}],
        }
        job = self.endpoint.ingest_message("order", payload, external_uid="EXT-MAP-1", source_ip="127.0.0.1")
        self.assertEqual(job.state, "done")
        self.assertTrue(job.request_id)
        self.assertEqual(job.request_id.patient_name, "Mapped Patient")

    def test_14_hl7_parser_order(self):
        adapter = self.env["lab.protocol.adapter"]
        hl7 = (
            "MSH|^~\\&|HIS|EXT|LIS|ODOO|20260220000000||ORM^O01|MSG001|P|2.5\r"
            "PID|||P1001||DOE^JOHN\r"
            "OBR|1|REQ1|REQ1|%s^GLUCOSE\r"
        ) % self.service.code
        parsed = adapter.parse_hl7_message(hl7)
        self.assertEqual(parsed["message_type"], "order")
        self.assertEqual(parsed["external_uid"], "MSG001")
        self.assertEqual(parsed["payload"]["lines"][0]["service_code"], self.service.code)

    def test_15_hl7_outbound_message_render(self):
        self.endpoint.protocol = "hl7v2"
        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [(0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1})],
            }
        )
        request.action_submit()
        job = request.interface_job_ids[:1]
        job.action_process()
        self.assertEqual(job.state, "done")
        self.assertIn("MSH|", job.response_body or "")
        self.assertIn("ORM^O01", job.response_body or "")

    def test_16_fhir_parser_observation(self):
        adapter = self.env["lab.protocol.adapter"]
        payload = {
            "resourceType": "Observation",
            "id": "obs-001",
            "identifier": [{"value": "ACC-001"}],
            "code": {"coding": [{"code": self.service.code}]},
            "valueString": "7.2",
        }
        parsed = adapter.parse_fhir_resource(payload)
        self.assertEqual(parsed["message_type"], "result")
        self.assertEqual(parsed["payload"]["results"][0]["service_code"], self.service.code)
        self.assertEqual(parsed["payload"]["results"][0]["result"], "7.2")

    def test_17_hl7_field_level_map(self):
        adapter = self.env["lab.protocol.adapter"]
        hl7 = (
            "MSH|^~\\&|HIS|EXT|LIS|ODOO|20260220000000||ORU^R01|MSG-FLD-1|P|2.5\r"
            "PID|||P1001||DOE^JANE\r"
            "OBR|1|REQ1|ACC-FLD-1|%s^GLUCOSE\r"
            "OBX|1|ST|%s^GLUCOSE||8.1|||N\r"
        ) % (self.service.code, self.service.code)
        parsed = adapter.parse_hl7_message(
            hl7,
            field_map={
                "patient_name": "PID.5.2",
                "accession": "OBR.3",
            },
        )
        self.assertEqual(parsed["payload"]["patient_name"], "JANE")
        self.assertEqual(parsed["payload"]["accession"], "ACC-FLD-1")

    def test_18_fhir_profile_validation_error(self):
        adapter = self.env["lab.protocol.adapter"]
        with self.assertRaises(ValidationError):
            adapter.parse_fhir_resource({"resourceType": "Observation", "id": "bad-1"})

    def test_19_interface_audit_logs_created(self):
        initial = self.env["lab.interface.audit.log"].search_count([])
        payload = {
            "patient_name": "Audit Patient",
            "priority": "routine",
            "sample_type": "blood",
            "lines": [{"service_code": self.service.code, "qty": 1}],
        }
        job = self.endpoint.ingest_message("order", payload, external_uid="EXT-AUD-1", source_ip="127.0.0.1")
        self.assertEqual(job.state, "done")
        after = self.env["lab.interface.audit.log"].search_count([])
        self.assertGreater(after, initial)
