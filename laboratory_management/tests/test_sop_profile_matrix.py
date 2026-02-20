from datetime import datetime

from odoo.tests.common import TransactionCase


class TestSopProfileMatrix(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env["res.partner"].create({"name": "Profile Matrix Patient", "lang": "en_US"})
        cls.client = cls.env["res.partner"].create({"name": "Matrix Hospital", "lang": "en_US"})

        cls.service = cls.env["lab.service"].create(
            {
                "name": "Matrix Glucose",
                "code": "MX-GLU",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 70,
                "ref_max": 110,
                "critical_min": 40,
                "critical_max": 450,
                "turnaround_hours": 3,
                "list_price": 28,
            }
        )
        cls.service_alt = cls.env["lab.service"].create(
            {
                "name": "Matrix Creatinine",
                "code": "MX-CREA",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 0.6,
                "ref_max": 1.2,
                "critical_min": 0.2,
                "critical_max": 8.0,
                "turnaround_hours": 3,
                "list_price": 30,
            }
        )

        cls.sop_regular = cls.env["lab.department.sop"].create(
            {
                "name": "Chem SOP Regular",
                "code": "MX-SOP-REG",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "all",
                "state": "active",
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register", "workstation_role": "reception"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analysis", "workstation_role": "analyst"}),
                ],
            }
        )
        cls.sop_institution_stat = cls.env["lab.department.sop"].create(
            {
                "name": "Chem SOP Institution STAT",
                "code": "MX-SOP-INS-STAT",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "stat",
                "state": "active",
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register", "workstation_role": "reception"}),
                    (0, 0, {"sequence": 15, "step_code": "precheck", "name": "Precheck", "workstation_role": "reviewer"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analysis", "workstation_role": "analyst"}),
                ],
            }
        )
        cls.service.sop_id = cls.sop_regular

        cls.strategy = cls.env["lab.sop.retest.strategy"].create(
            {
                "name": "Matrix Fallback Strategy",
                "code": "MX-STRAT",
                "department": "chemistry",
                "sample_type": "other",
                "max_total_attempts": 3,
                "line_ids": [
                    (0, 0, {"sequence": 10, "trigger": "qc_reject", "action": "escalate"}),
                ],
            }
        )

    def _create_sample(
        self,
        *,
        request_type="individual",
        priority="routine",
        service=None,
        fasting_required=False,
        requested_collection_date=False,
    ):
        service = service or self.service
        req_vals = {
            "requester_partner_id": self.patient.id,
            "request_type": request_type,
            "patient_id": self.patient.id,
            "patient_name": self.patient.name,
            "priority": priority,
            "sample_type": "blood",
            "fasting_required": fasting_required,
            "requested_collection_date": requested_collection_date or datetime(2026, 2, 20, 10, 0, 0),
            "line_ids": [
                (0, 0, {"line_type": "service", "service_id": service.id, "quantity": 1, "unit_price": service.list_price})
            ],
        }
        if request_type == "institution":
            req_vals["client_partner_id"] = self.client.id

        req = self.env["lab.test.request"].create(req_vals)
        req.action_submit()
        req.action_prepare_quote()
        req.action_approve_quote()
        req.action_create_samples()
        return req.sample_ids[:1]

    def test_01_workflow_profile_selects_target_sop(self):
        profile = self.env["lab.sop.workflow.profile"].create(
            {
                "name": "Institution STAT Chemistry",
                "code": "MX-PROFILE-1",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "stat",
                "request_type": "institution",
                "client_required": True,
                "sop_id": self.sop_institution_stat.id,
                "retest_strategy_id": self.strategy.id,
            }
        )

        sample = self._create_sample(request_type="institution", priority="stat")
        sample.action_receive()

        self.assertEqual(sample.workflow_profile_id, profile)
        self.assertEqual(sample.sop_id, self.sop_institution_stat)
        self.assertEqual(sample.sop_execution_id.retest_strategy_id, self.strategy)

    def test_02_exception_decision_matrix_recollects(self):
        self.env["lab.sop.exception.decision"].create(
            {
                "name": "Delta Fail Recollect",
                "code": "MX-DECISION-1",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "all",
                "request_type": "all",
                "trigger": "delta_fail",
                "severity": "all",
                "action": "recollect",
                "stop_execution": True,
            }
        )

        sample = self._create_sample(request_type="individual", priority="routine")
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.action_fail_current_step(reason="delta outlier", trigger="delta_fail")

        self.assertEqual(sample.state, "draft")
        run = self.env["lab.sop.exception.decision.run"].search([
            ("execution_id", "=", execution.id),
            ("trigger", "=", "delta_fail"),
        ], limit=1)
        self.assertTrue(run)
        self.assertTrue(run.matched)
        self.assertEqual(run.result_action, "recollect")

    def test_03_no_decision_falls_back_to_strategy(self):
        sample = self._create_sample(request_type="individual", priority="routine")
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.retest_strategy_id = self.strategy

        execution.action_fail_current_step(reason="qc reject", trigger="qc_reject")

        run = self.env["lab.sop.exception.decision.run"].search([
            ("execution_id", "=", execution.id),
            ("trigger", "=", "qc_reject"),
        ], limit=1)
        self.assertTrue(run)
        self.assertFalse(run.matched)
        self.assertEqual(run.result_action, "manual_review")

        self.assertGreaterEqual(
            self.env["lab.sop.execution.event"].search_count(
                [("execution_id", "=", execution.id), ("event_type", "=", "route_escalate")]
            ),
            1,
        )

    def test_04_profile_matches_fasting_window_and_service_scope(self):
        day_profile = self.env["lab.sop.workflow.profile"].create(
            {
                "name": "Chem Day Fasting Glucose",
                "code": "MX-PROFILE-FAST-DAY",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "all",
                "request_type": "all",
                "fasting_rule": "required",
                "request_time_window": "day",
                "service_ids": [(6, 0, [self.service.id])],
                "sop_id": self.sop_institution_stat.id,
            }
        )

        sample_match = self._create_sample(
            request_type="individual",
            priority="routine",
            service=self.service,
            fasting_required=True,
            requested_collection_date=datetime(2026, 2, 20, 9, 15, 0),
        )
        sample_match.action_receive()
        self.assertEqual(sample_match.workflow_profile_id, day_profile)

        sample_not_fasting = self._create_sample(
            request_type="individual",
            priority="routine",
            service=self.service,
            fasting_required=False,
            requested_collection_date=datetime(2026, 2, 20, 9, 20, 0),
        )
        sample_not_fasting.action_receive()
        self.assertNotEqual(sample_not_fasting.workflow_profile_id, day_profile)

        sample_wrong_service = self._create_sample(
            request_type="individual",
            priority="routine",
            service=self.service_alt,
            fasting_required=True,
            requested_collection_date=datetime(2026, 2, 20, 9, 25, 0),
        )
        sample_wrong_service.action_receive()
        self.assertNotEqual(sample_wrong_service.workflow_profile_id, day_profile)

        sample_night = self._create_sample(
            request_type="individual",
            priority="routine",
            service=self.service,
            fasting_required=True,
            requested_collection_date=datetime(2026, 2, 20, 22, 10, 0),
        )
        sample_night.action_receive()
        self.assertNotEqual(sample_night.workflow_profile_id, day_profile)

    def test_05_exception_decision_threshold_profile_controls_match(self):
        threshold = self.env["lab.sop.decision.threshold.profile"].create(
            {
                "name": "Need Two Out Of Range",
                "code": "MX-THRESH-2OOR",
                "department": "chemistry",
                "min_out_of_range_count": 2,
            }
        )
        self.env["lab.sop.exception.decision"].create(
            {
                "name": "Threshold Escalate",
                "code": "MX-DECISION-THRESH",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "all",
                "request_type": "all",
                "trigger": "delta_fail",
                "severity": "all",
                "action": "escalate",
                "threshold_profile_id": threshold.id,
            }
        )

        sample = self._create_sample(request_type="individual", priority="routine")
        sample.action_receive()
        execution = sample.sop_execution_id

        analysis = sample.analysis_ids[:1]
        analysis.write({"result_value": "150", "state": "done"})
        execution.action_fail_current_step(reason="single out of range", trigger="delta_fail")
        first_run = self.env["lab.sop.exception.decision.run"].search(
            [("execution_id", "=", execution.id), ("trigger", "=", "delta_fail")],
            order="id asc",
            limit=1,
        )
        self.assertTrue(first_run)
        self.assertFalse(first_run.matched)

        self.env["lab.sample.analysis"].create(
            {
                "sample_id": sample.id,
                "service_id": self.service_alt.id,
                "state": "done",
                "result_value": "0.1",
            }
        )
        execution.action_fail_current_step(reason="two out of range", trigger="delta_fail")
        second_run = self.env["lab.sop.exception.decision.run"].search(
            [("execution_id", "=", execution.id), ("trigger", "=", "delta_fail")],
            order="id desc",
            limit=1,
        )
        self.assertTrue(second_run)
        self.assertTrue(second_run.matched)
        self.assertEqual(second_run.result_action, "escalate")
