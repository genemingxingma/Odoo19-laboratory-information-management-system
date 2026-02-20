from odoo import fields, models


class LabManualReviewDigestConfig(models.Model):
    _name = "lab.manual.review.digest.config"
    _description = "Manual Review Digest Configuration"

    name = fields.Char(default="Default", required=True)
    active = fields.Boolean(default=True)
    fallback_email = fields.Char(
        string="Fallback Recipient Email",
        help="Used when reviewer group has no users with email.",
    )
    subject_template = fields.Char(
        default="[Lab] Manual Review Daily Digest - {report_day}",
        required=True,
    )
    body_template = fields.Text(
        required=True,
        default=(
            "<p>Manual review digest for <strong>{report_day}</strong></p>"
            "<ul>"
            "<li>Completed yesterday: {completed_count}</li>"
            "<li>Pending now: {pending_count}</li>"
            "<li>Overdue now: {overdue_count}</li>"
            "</ul>"
            "<p>Completed reason breakdown:</p>"
            "{reason_html}"
        ),
    )
