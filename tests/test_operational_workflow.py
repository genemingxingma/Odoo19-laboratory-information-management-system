from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestOperationalWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Workflow Patient", "lang": "en_US"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "Workflow Potassium",
                "code": "WF-K",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 3.5,
                "ref_max": 5.2,
                "critical_min": 2.5,
                "critical_max": 6.5,
                "turnaround_hours": 2,
                "list_price": 20,
                "auto_verify_enabled": True,
                "auto_verify_allow_out_of_range": False,
            }
        )
        cls.sop = cls.env["lab.department.sop"].create(
            {
                "name": "Workflow SOP",
                "code": "WF-SOP-1",
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
                "name": "Workflow Endpoint",
                "code": "WF-ENDPOINT",
                "system_type": "his",
                "direction": "outbound",
                "protocol": "rest",
            }
        )

    def _create_sample(self):
        req = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "request_type": "individual",
                "patient_id": self.partner.id,
                "patient_name": self.partner.name,
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [
                    (0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1, "unit_price": 20.0})
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
        return sample

    def test_01_manual_review_creates_task(self):
        sample = self._create_sample()
        line = sample.analysis_ids[:1]
        line.result_value = "5.9"
        line.action_mark_done()

        self.assertTrue(line.needs_manual_review)
        task_count = self.env["lab.workstation.task"].search_count(
            [
                ("analysis_id", "=", line.id),
                ("workstation", "=", "review"),
                ("state", "not in", ("done", "cancel")),
            ]
        )
        self.assertGreaterEqual(task_count, 1)

    def test_02_verify_closes_review_tasks(self):
        sample = self._create_sample()
        line = sample.analysis_ids[:1]
        line.result_value = "5.9"
        line.action_mark_done()
        line.action_verify_result()

        open_tasks = self.env["lab.workstation.task"].search_count(
            [
                ("analysis_id", "=", line.id),
                ("state", "not in", ("done", "cancel")),
            ]
        )
        self.assertEqual(open_tasks, 0)

    def test_03_task_board_metrics(self):
        sample = self._create_sample()
        line = sample.analysis_ids[:1]
        line.result_value = "5.9"
        line.action_mark_done()

        wiz = self.env["lab.task.board.wizard"].create({"department": "chemistry", "workstation": "review"})
        wiz.action_refresh()
        self.assertGreaterEqual(wiz.new_count + wiz.assigned_count + wiz.in_progress_count + wiz.overdue_count, 1)

    def test_04_branch_rule_create_ncr(self):
        sample = self._create_sample()
        line = sample.analysis_ids[:1]
        rule = self.env["lab.sop.branch.rule"].create(
            {
                "name": "Critical Creates NCR",
                "code": "WF-BRANCH-NCR",
                "department": "chemistry",
                "sample_type": "all",
                "trigger_event": "analysis_done",
                "action_type": "create_ncr",
                "ncr_severity": "major",
            }
        )

        engine = self.env["lab.sop.branch.engine"]
        runs = engine.run_rules("analysis_done", sample, analysis=line)
        self.assertTrue(runs.filtered(lambda x: x.rule_id == rule and x.result_state == "executed"))
        self.assertGreaterEqual(self.env["lab.nonconformance"].search_count([("sample_id", "=", sample.id)]), 1)

    def test_05_interface_replay_batch(self):
        sample = self._create_sample()
        req = sample.request_id
        failed_job = self.env["lab.interface.job"].create(
            {
                "endpoint_id": self.endpoint.id,
                "direction": "outbound",
                "message_type": "order",
                "request_id": req.id,
                "state": "failed",
                "error_message": "mock failed",
                "processed_at": fields.Datetime.now(),
            }
        )

        batch = self.env["lab.interface.replay.batch"].create(
            {
                "name": "WF Replay",
                "endpoint_id": self.endpoint.id,
                "reason": "test replay",
                "include_failed": True,
                "include_dead_letter": False,
            }
        )
        batch.action_prepare()
        self.assertGreaterEqual(len(batch.line_ids), 1)

        batch.action_execute()
        line = batch.line_ids.filtered(lambda x: x.job_id == failed_job)[:1]
        self.assertTrue(line)
        self.assertIn(line.state, ("done", "failed"))

    def test_06_overdue_cron_marks_and_escalates(self):
        task = self.env["lab.workstation.task"].create(
            {
                "title": "Overdue Task",
                "source_model": "lab.sample",
                "source_res_id": 1,
                "department": "chemistry",
                "workstation": "review",
                "priority": "routine",
                "due_date": fields.Datetime.now() - timedelta(hours=2),
            }
        )
        self.env["lab.workstation.task"]._cron_mark_overdue()
        task.invalidate_recordset(["state", "escalated"])
        self.assertEqual(task.state, "overdue")
        self.assertTrue(task.escalated)
