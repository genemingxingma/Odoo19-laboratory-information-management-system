from odoo import fields
from odoo.tests.common import TransactionCase


class TestGovernancePlus(TransactionCase):
    def test_01_exception_template_new_version(self):
        tmpl = self.env["lab.department.exception.template"].create(
            {
                "name": "Versioned Template",
                "code": "EXC_VER_BASE",
                "department": "chemistry",
                "sample_type": "all",
                "trigger_event": "manual_review_required",
                "severity": "major",
                "route_action": "task",
            }
        )
        action = tmpl.action_new_version()
        self.assertEqual(action.get("res_model"), "lab.department.exception.template")
        new = self.env["lab.department.exception.template"].browse(action["res_id"])
        self.assertEqual(new.template_key, tmpl.template_key)
        self.assertGreater(new.version_no, tmpl.version_no)
        self.assertFalse(tmpl.active)
        self.assertEqual(tmpl.superseded_by_id, new)

    def test_02_permission_repair_plan_apply(self):
        custom_group = self.env["res.groups"].create({"name": "Repair Missing Group"})
        snap = self.env["lab.permission.audit.snapshot"].create(
            {
                "include_custom_groups": True,
                "additional_group_ids": [(6, 0, [custom_group.id])],
            }
        )
        snap.action_generate()
        self.assertGreater(snap.missing_count, 0)

        action = snap.action_create_repair_plan()
        repair = self.env["lab.permission.audit.repair"].browse(action["res_id"])
        self.assertGreaterEqual(repair.total_lines, 1)
        repair.action_apply()
        self.assertEqual(repair.state, "applied")

        matrix_row = self.env["lab.permission.matrix"].search(
            [
                ("group_id", "=", custom_group.id),
                ("workstation", "=", "review"),
            ],
            limit=1,
        )
        if repair.line_ids.filtered(lambda x: x.group_id == custom_group and x.workstation == "review"):
            self.assertTrue(matrix_row)

    def test_03_reconciliation_export_csv(self):
        report = self.env["lab.interface.reconciliation.report"].create(
            {
                "period_start": fields.Date.today(),
                "period_end": fields.Date.today(),
            }
        )
        self.env["lab.interface.reconciliation.report.line"].create(
            {
                "report_id": report.id,
                "code": "x",
                "name": "line",
                "expected_value": 1,
                "actual_value": 0,
                "delta_value": -1,
                "is_mismatch": True,
            }
        )
        wiz = self.env["lab.interface.reconciliation.export.wizard"].create({"report_id": report.id})
        wiz.action_generate_csv()
        self.assertTrue(wiz.file_data)
        self.assertTrue(wiz.file_name.endswith(".csv"))
