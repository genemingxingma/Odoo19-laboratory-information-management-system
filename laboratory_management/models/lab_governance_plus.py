import base64
import csv
import io

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabDepartmentExceptionTemplateVersionMixin(models.Model):
    _inherit = "lab.department.exception.template"

    template_key = fields.Char(index=True)
    version_no = fields.Integer(default=1, required=True)
    previous_version_id = fields.Many2one("lab.department.exception.template", ondelete="set null")
    superseded_by_id = fields.Many2one("lab.department.exception.template", ondelete="set null")
    effective_from = fields.Date(default=fields.Date.today)
    effective_to = fields.Date()
    is_current = fields.Boolean(compute="_compute_is_current", store=False)

    @api.depends("superseded_by_id", "active")
    def _compute_is_current(self):
        for rec in self:
            rec.is_current = bool(rec.active and not rec.superseded_by_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            code = vals.get("code") or "TEMPLATE"
            if not vals.get("template_key"):
                if "-V" in code:
                    vals["template_key"] = code.split("-V")[0]
                else:
                    vals["template_key"] = code
            vals.setdefault("version_no", 1)
        return super().create(vals_list)

    def _next_version_no(self):
        self.ensure_one()
        rows = self.search([("template_key", "=", self.template_key)])
        return max(rows.mapped("version_no") or [1]) + 1

    def action_new_version(self):
        self.ensure_one()
        next_v = self._next_version_no()
        new_code = "%s-V%s" % (self.template_key, next_v)
        new_vals = {
            "name": "%s v%s" % (self.name, next_v),
            "code": new_code,
            "template_key": self.template_key,
            "version_no": next_v,
            "previous_version_id": self.id,
            "superseded_by_id": False,
            "active": True,
            "effective_from": fields.Date.today(),
            "effective_to": False,
        }
        new = self.copy(new_vals)
        self.write(
            {
                "superseded_by_id": new.id,
                "active": False,
                "effective_to": fields.Date.today(),
            }
        )
        return {
            "name": _("Exception Template"),
            "type": "ir.actions.act_window",
            "res_model": "lab.department.exception.template",
            "res_id": new.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_activate_current(self):
        for rec in self:
            current = self.search(
                [
                    ("template_key", "=", rec.template_key),
                    ("id", "!=", rec.id),
                    ("active", "=", True),
                ]
            )
            if current:
                current.write(
                    {
                        "active": False,
                        "superseded_by_id": rec.id,
                        "effective_to": fields.Date.today(),
                    }
                )
            rec.write(
                {
                    "active": True,
                    "superseded_by_id": False,
                    "effective_to": False,
                }
            )
        return True

    def action_retire_template(self):
        self.write({"active": False, "effective_to": fields.Date.today()})
        return True


class LabPermissionAuditRepair(models.Model):
    _name = "lab.permission.audit.repair"
    _description = "Permission Audit Repair Plan"
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    snapshot_id = fields.Many2one("lab.permission.audit.snapshot", required=True, ondelete="cascade")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("prepared", "Prepared"),
            ("applied", "Applied"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
    )
    line_ids = fields.One2many("lab.permission.audit.repair.line", "repair_id", string="Lines")
    total_lines = fields.Integer(compute="_compute_totals")
    applied_lines = fields.Integer(compute="_compute_totals")
    note = fields.Text()

    @api.depends("line_ids.state")
    def _compute_totals(self):
        for rec in self:
            rec.total_lines = len(rec.line_ids)
            rec.applied_lines = len(rec.line_ids.filtered(lambda x: x.state == "applied"))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def action_prepare(self):
        for rec in self:
            rows = []
            for line in rec.snapshot_id.line_ids.filtered(lambda x: x.status in ("missing", "warning")):
                rows.append(
                    (
                        0,
                        0,
                        {
                            "snapshot_line_id": line.id,
                            "group_id": line.group_id.id,
                            "workstation": line.workstation,
                            "can_view": True,
                            "can_create": False,
                            "can_edit": False,
                            "can_approve": line.workstation in ("review", "quality", "integration"),
                            "can_release": line.workstation == "review",
                            "can_administer": line.workstation in ("integration", "quality"),
                        },
                    )
                )
            rec.write({"line_ids": [(5, 0, 0)] + rows, "state": "prepared"})
        return True

    def action_apply(self):
        matrix_obj = self.env["lab.permission.matrix"]
        for rec in self:
            if rec.state not in ("prepared", "draft"):
                continue
            for line in rec.line_ids.filtered(lambda x: x.state in ("draft", "error")):
                try:
                    row = matrix_obj.search(
                        [
                            ("group_id", "=", line.group_id.id),
                            ("workstation", "=", line.workstation),
                        ],
                        limit=1,
                    )
                    vals = {
                        "name": "%s/%s" % (line.group_id.display_name, line.workstation),
                        "group_id": line.group_id.id,
                        "workstation": line.workstation,
                        "can_view": line.can_view,
                        "can_create": line.can_create,
                        "can_edit": line.can_edit,
                        "can_approve": line.can_approve,
                        "can_release": line.can_release,
                        "can_administer": line.can_administer,
                    }
                    if row:
                        row.write(vals)
                    else:
                        matrix_obj.create(vals)
                    line.write({"state": "applied", "result_note": _("Applied")})
                except Exception as exc:  # noqa: BLE001
                    line.write({"state": "error", "result_note": str(exc)})
            rec.state = "applied"
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})


class LabPermissionAuditRepairLine(models.Model):
    _name = "lab.permission.audit.repair.line"
    _description = "Permission Audit Repair Line"
    _order = "id"

    repair_id = fields.Many2one("lab.permission.audit.repair", required=True, ondelete="cascade", index=True)
    snapshot_line_id = fields.Many2one("lab.permission.audit.snapshot.line", ondelete="set null")
    group_id = fields.Many2one("res.groups", required=True)
    workstation = fields.Selection(
        [
            ("accession", "Accession"),
            ("analysis", "Analysis"),
            ("review", "Review"),
            ("quality", "Quality"),
            ("integration", "Integration"),
            ("billing", "Billing"),
            ("portal", "Portal"),
        ],
        required=True,
    )
    can_view = fields.Boolean(default=True)
    can_create = fields.Boolean(default=False)
    can_edit = fields.Boolean(default=False)
    can_approve = fields.Boolean(default=False)
    can_release = fields.Boolean(default=False)
    can_administer = fields.Boolean(default=False)
    state = fields.Selection(
        [("draft", "Draft"), ("applied", "Applied"), ("error", "Error")],
        default="draft",
        required=True,
    )
    result_note = fields.Text()


class LabPermissionAuditSnapshotRepairMixin(models.Model):
    _inherit = "lab.permission.audit.snapshot"

    repair_plan_count = fields.Integer(compute="_compute_repair_plan_count")

    def _compute_repair_plan_count(self):
        obj = self.env["lab.permission.audit.repair"]
        for rec in self:
            rec.repair_plan_count = obj.search_count([("snapshot_id", "=", rec.id)])

    def action_create_repair_plan(self):
        self.ensure_one()
        repair = self.env["lab.permission.audit.repair"].create({"snapshot_id": self.id})
        repair.action_prepare()
        return {
            "name": _("Permission Repair Plan"),
            "type": "ir.actions.act_window",
            "res_model": "lab.permission.audit.repair",
            "res_id": repair.id,
            "view_mode": "form",
            "target": "current",
        }


class LabInterfaceReconciliationExportWizard(models.TransientModel):
    _name = "lab.interface.reconciliation.export.wizard"
    _description = "Interface Reconciliation Export Wizard"

    report_id = fields.Many2one("lab.interface.reconciliation.report", required=True)
    include_only_mismatch = fields.Boolean(default=False)
    file_data = fields.Binary(readonly=True)
    file_name = fields.Char(readonly=True)

    def action_generate_csv(self):
        self.ensure_one()
        rows = self.report_id.line_ids
        if self.include_only_mismatch:
            rows = rows.filtered(lambda x: x.is_mismatch)

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "code",
            "name",
            "expected_value",
            "actual_value",
            "delta_value",
            "is_mismatch",
            "sample",
            "detail",
        ])
        for line in rows:
            writer.writerow(
                [
                    line.code,
                    line.name,
                    line.expected_value,
                    line.actual_value,
                    line.delta_value,
                    "1" if line.is_mismatch else "0",
                    line.sample_id.name if line.sample_id else "",
                    line.detail or "",
                ]
            )

        data = base64.b64encode(buf.getvalue().encode("utf-8"))
        filename = "%s_reconciliation.csv" % (self.report_id.name or "reconciliation")
        self.write({"file_data": data, "file_name": filename})
        return {
            "name": _("Export Reconciliation CSV"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.reconciliation.export.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class LabInterfaceReconciliationReportExportMixin(models.Model):
    _inherit = "lab.interface.reconciliation.report"

    def action_open_export_wizard(self):
        self.ensure_one()
        wiz = self.env["lab.interface.reconciliation.export.wizard"].create({"report_id": self.id})
        return {
            "name": _("Export Reconciliation"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.reconciliation.export.wizard",
            "res_id": wiz.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_mismatch_lines(self):
        self.ensure_one()
        return {
            "name": _("Mismatch Lines"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.reconciliation.report.line",
            "view_mode": "list",
            "domain": [
                ("report_id", "=", self.id),
                ("is_mismatch", "=", True),
            ],
        }


class LabDepartmentExceptionTemplateCurrentMixin(models.AbstractModel):
    _inherit = "lab.sop.branch.engine"

    @api.model
    def run_rules(self, event, sample, analysis=False, interface_job=False, payload=False):
        runs = super().run_rules(event, sample, analysis=analysis, interface_job=interface_job, payload=payload)
        if runs.filtered(lambda x: x.result_state == "executed"):
            return runs

        template = self.env["lab.department.exception.template"].search(
            [
                ("active", "=", True),
                ("superseded_by_id", "=", False),
                ("department", "=", sample.sop_id.department if sample.sop_id else "other"),
                ("trigger_event", "=", event),
            ],
            order="sequence asc, version_no desc, id desc",
            limit=1,
        )
        if template:
            template.apply_exception(sample=sample, event=event, analysis=analysis, interface_job=interface_job)
        return runs
