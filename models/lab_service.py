from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabService(models.Model):
    _name = "lab.service"
    _description = "Laboratory Analysis Service"
    _inherit = ["lab.master.data.mixin"]
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    department = fields.Selection(selection="_selection_department", default=lambda self: self._default_department_code(), required=True)
    sample_type = fields.Selection(selection="_selection_sample_type", default=lambda self: self._default_sample_type_code(), required=True)
    result_type = fields.Selection(
        [("numeric", "Numeric"), ("text", "Text")],
        default="numeric",
        required=True,
    )
    unit_id = fields.Many2one(
        "lab.result.unit",
        string="Unit",
        ondelete="restrict",
        domain="[('active','=',True)]",
    )
    unit = fields.Char(related="unit_id.name", store=True, readonly=True)
    ref_min = fields.Float(string="Reference Min")
    ref_max = fields.Float(string="Reference Max")
    critical_min = fields.Float(string="Critical Min")
    critical_max = fields.Float(string="Critical Max")
    require_qc = fields.Boolean(string="Require QC Pass Before Result Release", default=False)
    require_reagent_lot = fields.Boolean(string="Require Reagent Lot", default=False)
    auto_verify_enabled = fields.Boolean(string="Enable Auto-Verification", default=False)
    auto_verify_allow_out_of_range = fields.Boolean(string="Allow Out-of-Range for Auto-Verification", default=False)
    auto_verify_require_qc_pass = fields.Boolean(string="Require QC Pass for Auto-Verification", default=True)
    require_method_validation = fields.Boolean(
        string="Require Approved Method Validation for Release",
        default=False,
    )
    auto_binary_enabled = fields.Boolean(
        string="Enable Binary Interpretation",
        default=False,
        help="Automatically interpret numeric result as Positive/Negative by threshold.",
    )
    auto_binary_cutoff = fields.Float(
        string="Binary Interpretation Cutoff",
        default=33.0,
        help="Threshold value for binary interpretation rule.",
    )
    auto_binary_negative_when_gte = fields.Boolean(
        string="Negative When Result >= Cutoff",
        default=True,
        help="If enabled: result >= cutoff is Negative, otherwise Positive.",
    )
    delta_check_enabled = fields.Boolean(string="Enable Delta Check", default=False)
    delta_check_method = fields.Selection(
        [("absolute", "Absolute Difference"), ("percent", "Percent Change")],
        string="Delta Check Method",
        default="absolute",
    )
    delta_check_threshold = fields.Float(
        string="Delta Threshold",
        help="Max allowed difference for automatic pass. "
        "Absolute method uses raw value difference; percent uses percentage change.",
    )
    turnaround_hours = fields.Integer(default=24)
    list_price = fields.Float(string="List Price", default=0.0)
    active = fields.Boolean(default=True)
    profile_only = fields.Boolean(
        string="Panel Only",
        default=False,
        help="If enabled, this service is hidden from standalone service selection and should be used via panels.",
    )
    note = fields.Text()

    @api.model
    def _map_unit_text_to_unit_id(self, vals):
        if vals.get("unit_id"):
            vals.pop("unit", None)
            return vals
        unit_text = (vals.get("unit") or "").strip()
        if not unit_text:
            return vals
        unit = self.env["lab.result.unit"].sudo().get_or_create_by_name(unit_text)
        if unit:
            vals["unit_id"] = unit.id
        vals.pop("unit", None)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._map_unit_text_to_unit_id(dict(vals)) for vals in vals_list]
        return super().create(vals_list)

    def write(self, vals):
        vals = self._map_unit_text_to_unit_id(dict(vals))
        return super().write(vals)

    @api.constrains("auto_binary_cutoff")
    def _check_auto_binary_cutoff(self):
        for rec in self:
            if rec.auto_binary_cutoff < 0:
                raise ValidationError(_("Binary interpretation cutoff must be non-negative."))
