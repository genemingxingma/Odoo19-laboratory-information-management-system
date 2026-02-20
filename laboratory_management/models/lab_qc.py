from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabQcMaterial(models.Model):
    _name = "lab.qc.material"
    _description = "QC Material"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    service_id = fields.Many2one("lab.service", required=True)
    lot_number = fields.Char()
    target_value = fields.Float(required=True)
    std_dev = fields.Float(required=True, default=1.0)
    active = fields.Boolean(default=True)
    note = fields.Text()


class LabQcRun(models.Model):
    _name = "lab.qc.run"
    _description = "QC Run"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    qc_material_id = fields.Many2one("lab.qc.material", required=True)
    service_id = fields.Many2one(related="qc_material_id.service_id", store=True)
    run_date = fields.Datetime(default=fields.Datetime.now, required=True)
    operator_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    result_value = fields.Float(required=True)
    z_score = fields.Float(compute="_compute_qc", store=True)
    status = fields.Selection(
        [("pass", "Pass"), ("warning", "Warning"), ("reject", "Reject")],
        compute="_compute_qc",
        store=True,
        tracking=True,
    )
    rule_triggered = fields.Char(compute="_compute_qc", store=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.qc.run") or "New"
        records = super().create(vals_list)
        records._auto_create_reject_nonconformance()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "status" in vals or "result_value" in vals or "qc_material_id" in vals:
            self._auto_create_reject_nonconformance()
        return res

    @api.depends("result_value", "qc_material_id.target_value", "qc_material_id.std_dev")
    def _compute_qc(self):
        for rec in self:
            std_dev = rec.qc_material_id.std_dev or 0.0
            if std_dev <= 0:
                rec.z_score = 0.0
                rec.status = "reject"
                rec.rule_triggered = "invalid_sd"
                continue

            z = (rec.result_value - rec.qc_material_id.target_value) / std_dev
            rec.z_score = z
            abs_z = abs(z)
            if abs_z > 3:
                rec.status = "reject"
                rec.rule_triggered = "13s"
            elif abs_z > 2:
                rec.status = "warning"
                rec.rule_triggered = "12s"
            else:
                rec.status = "pass"
                rec.rule_triggered = "in_control"

    @api.constrains("qc_material_id", "run_date")
    def _check_duplicate_timestamp(self):
        for rec in self:
            if not rec.qc_material_id or not rec.run_date:
                continue
            dup = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("qc_material_id", "=", rec.qc_material_id.id),
                    ("run_date", "=", rec.run_date),
                ]
            )
            if dup:
                raise ValidationError(_("A QC run already exists for this material at the same datetime."))

    def _auto_create_reject_nonconformance(self):
        ncr_obj = self.env["lab.nonconformance"]
        for rec in self:
            if rec.status != "reject":
                continue
            exists = ncr_obj.search(
                [
                    ("qc_run_id", "=", rec.id),
                    ("state", "in", ("draft", "open", "investigation", "capa")),
                ],
                limit=1,
            )
            if exists:
                continue
            title = _("QC Rejected: %s") % rec.service_id.name
            desc = _(
                "QC run %(run)s was rejected by rule %(rule)s (z-score=%(z)s)."
            ) % {"run": rec.name, "rule": rec.rule_triggered or "-", "z": f"{rec.z_score:.2f}"}
            ncr_obj.create(
                {
                    "title": title,
                    "description": desc,
                    "source_type": "qc",
                    "qc_run_id": rec.id,
                    "severity": "major",
                    "owner_id": rec.operator_id.id,
                    "state": "open",
                }
            )
