from odoo.tests.common import TransactionCase


class TestWorkstationGovernance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.group_lab_user = cls.env.ref("laboratory_management.group_lab_user")

        user_model = cls.env["res.users"].with_context(no_reset_password=True)
        cls.user_a = user_model.create(
            {
                "name": "Workstation User A",
                "login": "ws_user_a",
                "email": "ws_user_a@example.com",
                "group_ids": [(6, 0, [cls.group_lab_user.id])],
            }
        )
        cls.user_b = user_model.create(
            {
                "name": "Workstation User B",
                "login": "ws_user_b",
                "email": "ws_user_b@example.com",
                "group_ids": [(6, 0, [cls.group_lab_user.id])],
            }
        )

        cls.profile_a = cls.env["lab.workstation.role.profile"].create(
            {
                "name": "Chem Review A",
                "code": "WS-PROFILE-A",
                "department": "chemistry",
                "workstation": "review",
                "user_id": cls.user_a.id,
                "group_id": cls.group_lab_user.id,
                "max_open_tasks": 5,
                "routine_weight": 10,
                "urgent_weight": 30,
                "stat_weight": 60,
            }
        )
        cls.profile_b = cls.env["lab.workstation.role.profile"].create(
            {
                "name": "Chem Review B",
                "code": "WS-PROFILE-B",
                "department": "chemistry",
                "workstation": "review",
                "user_id": cls.user_b.id,
                "group_id": cls.group_lab_user.id,
                "max_open_tasks": 5,
                "routine_weight": 10,
                "urgent_weight": 30,
                "stat_weight": 60,
            }
        )

    def _create_task(self, title, **extra):
        vals = {
            "title": title,
            "source_model": "lab.sample",
            "source_res_id": 1,
            "department": "chemistry",
            "workstation": "review",
            "priority": "routine",
        }
        vals.update(extra)
        return self.env["lab.workstation.task"].create(vals)

    def test_01_profile_load_balances_to_lower_load_user(self):
        rule = self.env["lab.workstation.assignment.rule"].create(
            {
                "name": "Chem Review Rule",
                "code": "WS-RULE-LOAD",
                "department": "chemistry",
                "workstation": "review",
                "priority": "all",
                "required_group_id": self.group_lab_user.id,
                "mode": "profile_load",
            }
        )

        self._create_task("Existing-A-1", assigned_user_id=self.user_a.id, state="assigned")
        self._create_task("Existing-A-2", assigned_user_id=self.user_a.id, state="in_progress")
        self._create_task("Existing-B-1", assigned_user_id=self.user_b.id, state="assigned")

        task = self._create_task("Need Auto Assign", priority="urgent")
        task._try_auto_assign()

        task.invalidate_recordset(["assigned_user_id", "assignment_rule_id", "role_profile_id", "state"])
        self.assertEqual(task.assignment_rule_id, rule)
        self.assertEqual(task.assigned_user_id, self.user_b)
        self.assertEqual(task.role_profile_id, self.profile_b)
        self.assertEqual(task.state, "assigned")

    def test_02_round_robin_rotation(self):
        self.env["lab.workstation.assignment.rule"].create(
            {
                "name": "Chem Review RR",
                "code": "WS-RULE-RR",
                "department": "chemistry",
                "workstation": "review",
                "priority": "all",
                "required_group_id": self.group_lab_user.id,
                "mode": "round_robin",
            }
        )

        t1 = self._create_task("RR-1")
        t1._try_auto_assign()
        t2 = self._create_task("RR-2")
        t2._try_auto_assign()

        t1.invalidate_recordset(["assigned_user_id"])
        t2.invalidate_recordset(["assigned_user_id"])

        self.assertTrue(t1.assigned_user_id)
        self.assertTrue(t2.assigned_user_id)
        self.assertNotEqual(t1.assigned_user_id, t2.assigned_user_id)

    def test_03_fallback_to_group_auto_assign_when_no_rule(self):
        task = self._create_task("Fallback Assign", assigned_group_id=self.group_lab_user.id)
        task._try_auto_assign()

        task.invalidate_recordset(["assigned_user_id", "assignment_rule_id", "state"])
        self.assertTrue(task.assigned_user_id)
        self.assertFalse(task.assignment_rule_id)
        self.assertEqual(task.state, "assigned")
