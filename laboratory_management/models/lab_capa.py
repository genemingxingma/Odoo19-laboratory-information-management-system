from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabNonconformance(models.Model):
    _name = "lab.nonconformance"
    _description = "Laboratory Nonconformance / CAPA"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    title = fields.Char(required=True, tracking=True)
    description = fields.Text()
    source_type = fields.Selection(
        [
            ("manual", "Manual"),
            ("sample", "Sample"),
            ("analysis", "Analysis"),
            ("qc", "QC"),
        ],
        default="manual",
        required=True,
        tracking=True,
    )
    sample_id = fields.Many2one("lab.sample", tracking=True)
    analysis_id = fields.Many2one("lab.sample.analysis", tracking=True)
    qc_run_id = fields.Many2one("lab.qc.run", tracking=True)
    service_id = fields.Many2one("lab.service", compute="_compute_service_id", store=True)
    detected_date = fields.Datetime(default=fields.Datetime.now, required=True)
    detected_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    owner_id = fields.Many2one("res.users", string="CAPA Owner")
    severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="major",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("open", "Open"),
            ("investigation", "Investigation"),
            ("capa", "CAPA Planned"),
            ("closed", "Closed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )
    root_cause = fields.Text()
    immediate_action = fields.Text()
    corrective_action = fields.Text()
    preventive_action = fields.Text()
    effectiveness_check = fields.Text()
    due_date = fields.Date()
    close_note = fields.Text()
    closed_by_id = fields.Many2one("res.users", readonly=True)
    closed_date = fields.Datetime(readonly=True)

    _name_uniq = models.Constraint("unique(name)", "Nonconformance number must be unique.")

    @api.depends("analysis_id.service_id", "qc_run_id.service_id")
    def _compute_service_id(self):
        for rec in self:
            rec.service_id = rec.analysis_id.service_id or rec.qc_run_id.service_id

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.nonconformance") or "New"
        return super().create(vals_list)

    def action_open(self):
        self.write({"state": "open"})

    def action_start_investigation(self):
        self.write({"state": "investigation"})

    def action_plan_capa(self):
        self.write({"state": "capa"})

    def action_close(self):
        for rec in self:
            if not rec.corrective_action or not rec.preventive_action:
                raise UserError(_("Corrective and preventive actions are required before closing."))
            rec.write(
                {
                    "state": "closed",
                    "closed_by_id": self.env.user.id,
                    "closed_date": fields.Datetime.now(),
                }
            )

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
