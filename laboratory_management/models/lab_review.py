from odoo import fields, models


class LabReviewReasonTemplate(models.Model):
    _name = "lab.review.reason.template"
    _description = "Lab Review Reason Template"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("auto_disabled", "Auto-Verification Disabled"),
            ("critical", "Critical Result"),
            ("out_of_range", "Out of Reference Range"),
            ("qc_not_passed", "QC Not Passed"),
            ("delta_fail", "Delta Check Failed"),
        ],
        required=True,
    )
    message = fields.Text(required=True)
    recommendation = fields.Text(
        string="Recommended Review Action",
        help="Standard action guidance shown when this reason is triggered.",
    )
    append_to_result_note = fields.Boolean(
        string="Append Recommendation to Result Note",
        default=True,
    )
    sla_hours = fields.Integer(
        string="Review SLA (Hours)",
        default=2,
        help="Expected manual review completion window in hours.",
    )
    active = fields.Boolean(default=True)
