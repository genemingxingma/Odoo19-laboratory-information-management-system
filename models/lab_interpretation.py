from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabInterpretationProfile(models.Model):
    _name = "lab.interpretation.profile"
    _description = "Result Interpretation Profile"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    service_match_mode = fields.Selection(
        [("all_required", "All Rules Must Match"), ("any_required", "Any Rule Match")],
        default="all_required",
        required=True,
    )
    minimum_required_count = fields.Integer(
        default=0,
        help="If greater than 0, this many evaluated rules are enough to output Negative. 0 means all rules.",
    )
    positive_summary_template = fields.Char(
        default="Positive ({detected} detected)",
        required=True,
        help="Use {detected} placeholder for detected item labels.",
    )
    negative_summary_text = fields.Char(default="Negative", required=True)
    inconclusive_summary_text = fields.Char(default="Inconclusive", required=True)
    note = fields.Text()
    line_ids = fields.One2many("lab.interpretation.profile.line", "profile_id", string="Rules")

    _sql_constraints = [
        ("lab_interpretation_profile_code_uniq", "unique(code)", "Interpretation profile code must be unique."),
    ]

    @api.constrains("minimum_required_count")
    def _check_minimum_required_count(self):
        for rec in self:
            if rec.minimum_required_count < 0:
                raise ValidationError(_("Minimum required count must be >= 0."))

    def _service_ids(self):
        self.ensure_one()
        return set(self.line_ids.mapped("service_id").ids)

    def score_for_service_ids(self, sample_service_ids):
        self.ensure_one()
        profile_service_ids = self._service_ids()
        if not profile_service_ids:
            return -1
        sample_service_ids = set(sample_service_ids or [])
        overlap = profile_service_ids & sample_service_ids
        if self.service_match_mode == "all_required":
            if not profile_service_ids.issubset(sample_service_ids):
                return -1
        elif not overlap:
            return -1
        return len(overlap)


class LabInterpretationProfileLine(models.Model):
    _name = "lab.interpretation.profile.line"
    _description = "Result Interpretation Rule"
    _order = "sequence, id"

    profile_id = fields.Many2one("lab.interpretation.profile", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    service_id = fields.Many2one("lab.service", required=True, ondelete="restrict")
    label = fields.Char(help="Optional label used in detected items list. If empty, service name is used.")
    evaluation_mode = fields.Selection(
        [
            ("binary_positive", "Binary = Positive"),
            ("binary_negative", "Binary = Negative"),
            ("numeric_lt", "Numeric < Threshold"),
            ("numeric_lte", "Numeric <= Threshold"),
            ("numeric_gt", "Numeric > Threshold"),
            ("numeric_gte", "Numeric >= Threshold"),
            ("text_equals", "Text Equals"),
            ("text_contains", "Text Contains"),
        ],
        default="binary_positive",
        required=True,
    )
    threshold_float = fields.Float()
    threshold_text = fields.Char()
    include_in_detected = fields.Boolean(
        default=True,
        help="If checked and rule evaluates positive, add this rule label to detected items.",
    )
    active = fields.Boolean(default=True)

    @api.constrains("evaluation_mode", "threshold_text")
    def _check_text_threshold(self):
        for rec in self:
            if rec.evaluation_mode in ("text_equals", "text_contains") and not (rec.threshold_text or "").strip():
                raise ValidationError(_("Text threshold is required for text-based interpretation rules."))

