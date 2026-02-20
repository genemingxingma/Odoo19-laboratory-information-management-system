from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestSopAdvancedGovernance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env["res.partner"].create({"name": "Advanced SOP Patient", "lang": "en_US"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "Advanced Calcium",
                "code": "ADV-CA",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 8.5,
                "ref_max": 10.5,
                "critical_min": 6.5,
                "critical_max": 14.0,
                "turnaround_hours": 2,
                "list_price": 33,
            }
        )
        cls.sop = cls.env["lab.department.sop"].create(
            {
                "name": "Advanced SOP",
                "code": "ADV-SOP-1",
                "department": "chemistry",
                "sample_type": "blood",
                "state": "active",
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register", "workstation_role": "reception"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analysis", "workstation_role": "analyst"}),
                ],
                "exception_route_ids": [
                    (0, 0, {"sequence": 10, "trigger_event": "delta_fail", "severity": "major", "route_action": "manual_review"}),
                ],
            }
        )
        cls.service.sop_id = cls.sop

    def _create_sample(self):
        req = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.patient.id,
                "request_type": "individual",
                "patient_id": self.patient.id,
                "patient_name": self.patient.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [
                    (0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1, "unit_price": 33.0})
                ],
            }
        )
        req.action_submit()
        req.action_prepare_quote()
        req.action_approve_quote()
        req.action_create_samples()
        return req.sample_ids[:1]

    def test_01_sop_version_capture_and_apply(self):
        version = self.env["lab.department.sop.version"].create_from_sop(self.sop, note="baseline")
        self.assertEqual(version.version_no, 1)
        self.assertEqual(version.state, "draft")

        self.sop.write(
            {
                "step_ids": [
                    (5, 0, 0),
                    (0, 0, {"sequence": 10, "step_code": "intake", "name": "Intake", "workstation_role": "reception"}),
                    (0, 0, {"sequence": 30, "step_code": "verify", "name": "Verify", "workstation_role": "reviewer"}),
                ]
            }
        )
        self.assertEqual(len(self.sop.step_ids), 2)
        self.assertEqual(self.sop.step_ids.sorted("sequence")[0].step_code, "intake")

        version.action_approve()
        version.action_apply_to_sop()
        self.sop.invalidate_recordset(["step_ids"])
        self.assertEqual(self.sop.step_ids.sorted("sequence")[0].step_code, "register")

    def test_02_exception_sla_cron_escalates(self):
        self.env["lab.sop.exception.decision"].create(
            {
                "name": "SLA Escalate Decision",
                "code": "ADV-DECISION-SLA",
                "department": "chemistry",
                "sample_type": "blood",
                "priority": "all",
                "request_type": "all",
                "trigger": "delta_fail",
                "severity": "all",
                "action": "manual_review",
                "sla_hours": 1,
            }
        )

        sample = self._create_sample()
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.action_fail_current_step(reason="delta deviation", trigger="delta_fail")
        self.assertTrue(execution.exception_deadline)

        execution.write({
            "exception_deadline": fields.Datetime.now() - timedelta(hours=2),
            "exception_escalated": False,
        })
        self.env["lab.sop.exception.sla.monitor"]._cron_escalate_overdue_sop_exceptions()
        execution.invalidate_recordset(["exception_escalated", "exception_escalated_at"])

        self.assertTrue(execution.exception_escalated)
        self.assertTrue(execution.exception_escalated_at)
        self.assertGreaterEqual(self.env["lab.nonconformance"].search_count([("sample_id", "=", sample.id)]), 1)

    def test_03_retest_analytics_report_generate(self):
        sample = self._create_sample()
        sample.action_receive()
        line = sample.analysis_ids[:1]
        line.write({"state": "done", "result_value": "15.1", "delta_check_value": 2.4})
        line.with_context(skip_retest_policy_check=True).action_request_retest()

        report = self.env["lab.retest.analytics.report"].create(
            {
                "start_date": fields.Date.today() - timedelta(days=1),
                "end_date": fields.Date.today() + timedelta(days=1),
                "department": "chemistry",
            }
        )
        report.action_generate()

        self.assertGreaterEqual(report.total_retests, 1)
        self.assertGreaterEqual(report.sample_count, 1)
        self.assertGreaterEqual(len(report.line_ids), 1)
