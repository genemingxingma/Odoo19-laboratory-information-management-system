from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestGovernanceExtension(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Governance Patient", "lang": "en_US"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "Governance Calcium",
                "code": "GV-CA",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 8.4,
                "ref_max": 10.2,
                "turnaround_hours": 4,
                "list_price": 25,
                "auto_verify_enabled": False,
            }
        )
        cls.sop = cls.env["lab.department.sop"].create(
            {
                "name": "Governance SOP",
                "code": "GV-SOP-1",
                "department": "chemistry",
                "state": "active",
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analysis"}),
                ],
            }
        )
        cls.service.sop_id = cls.sop

        cls.endpoint = cls.env["lab.interface.endpoint"].create(
            {
                "name": "Governance Endpoint",
                "code": "GV-ENDPOINT",
                "system_type": "his",
                "direction": "outbound",
                "protocol": "rest",
            }
        )

    def _create_reported_sample(self):
        req = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_id": self.partner.id,
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [
                    (0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1, "unit_price": 25.0})
                ],
            }
        )
        req.action_submit()
        req.action_prepare_quote()
        req.action_approve_quote()
        req.action_create_samples()

        sample = req.sample_ids[:1]
        sample.action_receive()
        sample.action_start()
        line = sample.analysis_ids[:1]
        line.result_value = "9.1"
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
        return sample

    def test_01_permission_audit_snapshot_detects_missing(self):
        custom_group = self.env["res.groups"].create({"name": "Custom Missing Matrix Group"})
        snap = self.env["lab.permission.audit.snapshot"].create(
            {
                "include_custom_groups": True,
                "additional_group_ids": [(6, 0, [custom_group.id])],
            }
        )
        snap.action_generate()
        missing = snap.line_ids.filtered(lambda x: x.group_id == custom_group and x.status == "missing")
        self.assertTrue(missing)

    def test_02_permission_audit_wizard_generates_snapshot(self):
        wizard = self.env["lab.permission.audit.wizard"].create({"include_custom_groups": False})
        action = wizard.action_generate_snapshot()
        self.assertTrue(wizard.snapshot_id)
        self.assertEqual(action.get("res_model"), "lab.permission.audit.snapshot")

    def test_03_interface_reconciliation_report(self):
        sample = self._create_reported_sample()
        self.env["lab.interface.job"].create(
            {
                "endpoint_id": self.endpoint.id,
                "direction": "outbound",
                "message_type": "report",
                "sample_id": sample.id,
                "request_id": sample.request_id.id,
                "state": "done",
                "processed_at": fields.Datetime.now(),
            }
        )
        report = self.env["lab.interface.reconciliation.report"].create(
            {
                "period_start": fields.Date.today(),
                "period_end": fields.Date.today(),
                "endpoint_id": self.endpoint.id,
            }
        )
        report.action_generate()
        self.assertGreaterEqual(report.total_lines, 1)
        self.assertTrue(report.line_ids.filtered(lambda x: x.code == "report_delivery"))

    def test_04_exception_template_apply_creates_task(self):
        sample = self._create_reported_sample()
        line = sample.analysis_ids[:1]
        line.write({"needs_manual_review": True})
        sample.action_apply_exception_template()

        count = self.env["lab.workstation.task"].search_count(
            [
                ("sample_id", "=", sample.id),
                ("workstation", "=", "review"),
                ("state", "not in", ("done", "cancel")),
            ]
        )
        self.assertGreaterEqual(count, 1)

    def test_05_governance_workbench_metrics(self):
        self.env["lab.workstation.task"].create(
            {
                "title": "Governance Overdue",
                "source_model": "lab.sample",
                "source_res_id": 1,
                "department": "chemistry",
                "workstation": "review",
                "priority": "routine",
                "due_date": fields.Datetime.now() - timedelta(hours=3),
                "state": "overdue",
                "escalated": True,
            }
        )
        snap = self.env["lab.permission.audit.snapshot"].create({})
        snap.action_generate()

        wiz = self.env["lab.governance.workbench.wizard"].create({"period_days": 30})
        wiz.action_refresh()
        self.assertGreaterEqual(wiz.task_overdue_count, 1)
        self.assertGreaterEqual(wiz.task_escalated_count, 1)

    def test_06_branch_engine_fallback_exception_template(self):
        sample = self._create_reported_sample()
        line = sample.analysis_ids[:1]
        line.write({"needs_manual_review": True})

        self.env["lab.sop.branch.rule"].search([("department", "=", "chemistry"), ("trigger_event", "=", "manual_review_required")]).write({"active": False})
        self.env["lab.sop.branch.engine"].run_rules("manual_review_required", sample, analysis=line)

        task = self.env["lab.workstation.task"].search(
            [
                ("sample_id", "=", sample.id),
                ("workstation", "=", "review"),
            ],
            limit=1,
        )
        self.assertTrue(task)
