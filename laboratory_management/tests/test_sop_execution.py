from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestSopExecution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "SOP Exec Patient", "lang": "en_US"})
        cls.service = cls.env["lab.service"].create(
            {
                "name": "Execution Sodium",
                "code": "EXEC-NA",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "ref_min": 130,
                "ref_max": 145,
                "critical_min": 120,
                "critical_max": 160,
                "turnaround_hours": 2,
                "list_price": 10,
                "auto_verify_enabled": False,
            }
        )
        cls.sop = cls.env["lab.department.sop"].create(
            {
                "name": "Exec SOP",
                "code": "EXEC-SOP-1",
                "department": "chemistry",
                "state": "active",
                "step_ids": [
                    (0, 0, {"sequence": 10, "step_code": "register", "name": "Register", "workstation_role": "reception"}),
                    (0, 0, {"sequence": 20, "step_code": "analysis", "name": "Analysis", "workstation_role": "analyst"}),
                    (0, 0, {"sequence": 30, "step_code": "verify", "name": "Verify", "workstation_role": "reviewer"}),
                ],
            }
        )
        cls.service.sop_id = cls.sop

        cls.strategy = cls.env["lab.sop.retest.strategy"].create(
            {
                "name": "Exec Strategy",
                "code": "EXEC-STRAT-1",
                "department": "chemistry",
                "sample_type": "other",
                "max_total_attempts": 2,
                "cooldown_minutes": 0,
                "recollect_after_attempt": 2,
                "escalate_after_attempt": 2,
                "owner_group_id": cls.env.ref("laboratory_management.group_lab_manager").id,
                "line_ids": [
                    (0, 0, {"sequence": 10, "trigger": "manual_review_reject", "action": "retest", "max_attempt": 1}),
                    (0, 0, {"sequence": 20, "trigger": "qc_reject", "action": "escalate"}),
                ],
            }
        )

        cls.review_matrix = cls.env["lab.permission.matrix"].search(
            [("workstation", "=", "review"), ("group_id", "=", cls.env.ref("laboratory_management.group_lab_manager").id)],
            limit=1,
        )
        if not cls.review_matrix:
            cls.review_matrix = cls.env["lab.permission.matrix"].create(
                {
                    "name": "Manager Review Access",
                    "group_id": cls.env.ref("laboratory_management.group_lab_manager").id,
                    "workstation": "review",
                    "can_view": True,
                    "can_create": True,
                    "can_edit": True,
                    "can_approve": True,
                    "can_release": True,
                    "can_administer": True,
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
                    (0, 0, {"line_type": "service", "service_id": self.service.id, "quantity": 1, "unit_price": 10.0})
                ],
            }
        )
        req.action_submit()
        req.action_prepare_quote()
        req.action_approve_quote()
        req.action_create_samples()
        sample = req.sample_ids[:1]
        return sample

    def test_01_receive_creates_execution(self):
        sample = self._create_sample()
        sample.action_receive()
        self.assertTrue(sample.sop_execution_id)
        self.assertEqual(sample.sop_execution_id.state, "running")
        self.assertEqual(sample.sop_execution_id.sop_id, self.sop)
        self.assertEqual(sample.sop_execution_id.current_step_id.step_code, "register")

    def test_02_complete_steps_until_finished(self):
        sample = self._create_sample()
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.action_complete_current_step(note="step-1")
        self.assertEqual(execution.current_step_id.step_code, "analysis")
        execution.action_complete_current_step(note="step-2")
        self.assertEqual(execution.current_step_id.step_code, "verify")
        execution.action_complete_current_step(note="step-3")
        self.assertEqual(execution.state, "completed")

    def test_03_fail_current_step_routes_manual_review(self):
        sample = self._create_sample()
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.retest_strategy_id = self.strategy
        execution.action_fail_current_step(reason="delta anomaly", trigger="delta_fail")
        self.assertEqual(execution.state, "exception")
        self.assertTrue(
            self.env["lab.sop.execution.event"].search_count(
                [("execution_id", "=", execution.id), ("event_type", "=", "route_manual_review")]
            )
            >= 1
        )

    def test_04_retest_route_creates_retest_line(self):
        sample = self._create_sample()
        sample.action_receive()
        sample.action_start()
        line = sample.analysis_ids[:1]
        line.result_value = "150"
        line.action_mark_done()

        execution = sample.sop_execution_id
        execution.retest_strategy_id = self.strategy
        execution.action_fail_current_step(reason="manual reject", trigger="manual_review_reject")

        self.assertGreaterEqual(len(sample.analysis_ids.filtered(lambda x: x.is_retest)), 1)

    def test_05_escalate_route_creates_ncr(self):
        sample = self._create_sample()
        sample.action_receive()
        execution = sample.sop_execution_id
        execution.retest_strategy_id = self.strategy
        execution.action_fail_current_step(reason="qc rejected", trigger="qc_reject")
        self.assertEqual(sample.sop_exception_state, "escalated")
        self.assertGreaterEqual(
            self.env["lab.nonconformance"].search_count([("sample_id", "=", sample.id)]),
            1,
        )

    def test_06_permission_matrix_blocks_verify_without_approve_right(self):
        sample = self._create_sample()
        sample.action_receive()
        sample.action_start()
        line = sample.analysis_ids[:1]
        line.result_value = "140"
        line.action_verify_result()
        own_group = self.env.user.group_ids[:1]
        deny_matrix = self.env["lab.permission.matrix"].search(
            [("workstation", "=", "review"), ("group_id", "=", own_group.id)],
            limit=1,
        )
        if not deny_matrix:
            deny_matrix = self.env["lab.permission.matrix"].create(
                {
                    "name": "Runtime Deny Review",
                    "group_id": own_group.id,
                    "workstation": "review",
                    "can_view": True,
                    "can_create": False,
                    "can_edit": False,
                    "can_approve": False,
                    "can_release": False,
                    "can_administer": False,
                }
            )
        else:
            deny_matrix.write({"can_approve": False})
        with self.assertRaises(UserError):
            sample.action_verify()

    def test_07_permission_matrix_allows_release_with_rights(self):
        sample = self._create_sample()
        sample.action_receive()
        sample.action_start()
        sample.analysis_ids[:1].write({"result_value": "140"})
        sample.analysis_ids[:1].action_verify_result()

        own_group = self.env.user.group_ids[:1]
        allow_matrix = self.env["lab.permission.matrix"].search(
            [("workstation", "=", "review"), ("group_id", "=", own_group.id)],
            limit=1,
        )
        if not allow_matrix:
            allow_matrix = self.env["lab.permission.matrix"].create(
                {
                    "name": "Runtime Allow Review",
                    "group_id": own_group.id,
                    "workstation": "review",
                    "can_view": True,
                    "can_create": True,
                    "can_edit": True,
                    "can_approve": True,
                    "can_release": True,
                    "can_administer": True,
                }
            )
        else:
            allow_matrix.write({"can_approve": True, "can_release": True})
        sample.action_verify()
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
        self.assertEqual(sample.state, "reported")

    def test_08_dashboard_metrics(self):
        sample = self._create_sample()
        sample.action_receive()
        wizard = self.env["lab.sop.execution.dashboard.wizard"].create(
            {"department": "chemistry", "period_days": 60}
        )
        wizard.action_refresh()
        self.assertGreaterEqual(wizard.total_execution, 1)
        self.assertGreaterEqual(wizard.running_execution, 1)

    def test_09_claim_and_skip_step(self):
        sample = self._create_sample()
        sample.action_receive()
        execution = sample.sop_execution_id
        step = execution.current_step_id
        step.action_claim()
        self.assertEqual(step.state, "running")
        optional = self.env["lab.sop.execution.step"].create(
            {
                "execution_id": execution.id,
                "step_code": "optional_check",
                "name": "Optional Check",
                "workstation_role": "analyst",
                "required": False,
                "sequence": 99,
                "state": "ready",
            }
        )
        optional.action_skip()
        self.assertEqual(optional.state, "skipped")

    def test_10_retest_rule_tiered_by_attempt_count(self):
        strategy = self.env["lab.sop.retest.strategy"].create(
            {
                "name": "Tiered Attempt Strategy",
                "code": "EXEC-STRAT-TIER",
                "department": "chemistry",
                "sample_type": "other",
                "max_total_attempts": 5,
                "line_ids": [
                    (0, 0, {"sequence": 10, "trigger": "delta_fail", "action": "manual_review", "min_attempt": 1}),
                    (0, 0, {"sequence": 20, "trigger": "delta_fail", "action": "retest"}),
                ],
            }
        )

        sample = self._create_sample()
        sample.action_receive()
        sample.action_start()
        sample.analysis_ids[:1].write({"result_value": "150"})
        sample.analysis_ids[:1].action_mark_done()

        execution = sample.sop_execution_id
        execution.retest_strategy_id = strategy
        execution.action_fail_current_step(reason="first delta fail", trigger="delta_fail")
        self.assertGreaterEqual(len(sample.analysis_ids.filtered(lambda x: x.is_retest)), 1)

        execution.action_fail_current_step(reason="second delta fail", trigger="delta_fail")
        self.assertGreaterEqual(
            self.env["lab.sop.execution.event"].search_count(
                [("execution_id", "=", execution.id), ("event_type", "=", "route_manual_review")]
            ),
            1,
        )

    def test_11_retest_rule_overlap_warning_and_duplicate_guard(self):
        strategy = self.env["lab.sop.retest.strategy"].create(
            {
                "name": "Overlap Strategy",
                "code": "EXEC-STRAT-OVERLAP",
                "department": "chemistry",
                "sample_type": "other",
                "max_total_attempts": 5,
                "line_ids": [
                    (0, 0, {"sequence": 10, "trigger": "delta_fail", "action": "manual_review"}),
                    (0, 0, {"sequence": 20, "trigger": "delta_fail", "action": "retest", "min_attempt": 1}),
                ],
            }
        )
        strategy.flush_recordset()
        self.assertGreaterEqual(strategy.rule_warning_count, 1)
        self.assertTrue(any(strategy.line_ids.filtered(lambda x: x.sequence == 20).mapped("has_overlap")))

        with self.assertRaises(ValidationError):
            self.env["lab.sop.retest.strategy.line"].create(
                {
                    "strategy_id": strategy.id,
                    "sequence": 99,
                    "trigger": "delta_fail",
                    "severity": "all",
                    "action": "retest",
                    "min_attempt": 0,
                    "max_attempt": 0,
                }
            )
