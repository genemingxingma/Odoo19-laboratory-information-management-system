from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabWorksheet(models.Model):
    _name = "lab.worksheet"
    _description = "Laboratory Worksheet"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
        required=True,
        default="chemistry",
    )
    analyst_id = fields.Many2one("res.users", string="Primary Analyst")
    planned_date = fields.Datetime(default=fields.Datetime.now)
    state = fields.Selection(
        [("draft", "Draft"), ("in_progress", "In Progress"), ("done", "Done")],
        default="draft",
        tracking=True,
    )
    analysis_ids = fields.One2many("lab.sample.analysis", "worksheet_id", string="Worksheet Analyses")
    note = fields.Text()

    total_analysis = fields.Integer(compute="_compute_counts", store=True)
    done_analysis = fields.Integer(compute="_compute_counts", store=True)

    @api.depends("analysis_ids.state")
    def _compute_counts(self):
        for rec in self:
            rec.total_analysis = len(rec.analysis_ids)
            rec.done_analysis = len(rec.analysis_ids.filtered(lambda x: x.state in ("done", "verified")))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.worksheet") or "New"
        return super().create(vals_list)

    def action_load_pending(self):
        for rec in self:
            domain = [
                ("worksheet_id", "=", False),
                ("state", "in", ("pending", "assigned")),
                ("department", "=", rec.department),
            ]
            lines = self.env["lab.sample.analysis"].search(domain, limit=200)
            if not lines:
                raise UserError(_("No pending analyses found for this department."))
            vals = {"worksheet_id": rec.id, "state": "assigned"}
            if rec.analyst_id:
                vals["analyst_id"] = rec.analyst_id.id
            lines.write(vals)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_done(self):
        for rec in self:
            not_done = rec.analysis_ids.filtered(lambda x: x.state not in ("done", "verified"))
            if not_done:
                raise UserError(_("There are unfinished analyses in this worksheet."))
            rec.state = "done"
