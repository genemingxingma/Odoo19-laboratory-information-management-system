from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabTrainingAuthorizationTemplate(models.Model):
    _name = "lab.training.authorization.template"
    _description = "Training Authorization Template"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many(
        "lab.training.authorization.template.line",
        "template_id",
        string="Template Lines",
    )
    note = fields.Text()

    _code_unique = models.Constraint(
        "unique(code)",
        "Training authorization template code must be unique.",
    )

    @api.constrains("line_ids")
    def _check_lines(self):
        for rec in self:
            if not rec.line_ids:
                raise ValidationError(_("Training authorization template must include at least one line."))


class LabTrainingAuthorizationTemplateLine(models.Model):
    _name = "lab.training.authorization.template.line"
    _description = "Training Authorization Template Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one(
        "lab.training.authorization.template",
        required=True,
        ondelete="cascade",
        index=True,
    )
    role = fields.Selection(
        [
            ("analyst", "Analyst"),
            ("technical_reviewer", "Technical Reviewer"),
            ("medical_reviewer", "Medical Reviewer"),
        ],
        required=True,
        default="analyst",
    )
    service_ids = fields.Many2many(
        "lab.service",
        "lab_training_auth_template_line_service_rel",
        "line_id",
        "service_id",
        string="Services",
    )
    effective_months = fields.Integer(default=12)

    @api.constrains("effective_months")
    def _check_effective_months(self):
        for rec in self:
            if rec.effective_months < 0:
                raise ValidationError(_("Effective months must be zero or positive."))


class LabQualityTrainingTemplateMixin(models.Model):
    _inherit = "lab.quality.training"

    authorization_template_id = fields.Many2one(
        "lab.training.authorization.template",
        string="Authorization Template",
    )

    def action_apply_authorization_template(self):
        for rec in self:
            tpl = rec.authorization_template_id
            if not tpl:
                raise UserError(_("Please select an authorization template first."))
            if not tpl.line_ids:
                raise UserError(_("Selected authorization template has no lines."))

            # Training record supports a single role + service set for batch generation.
            # If template has multiple roles, user can apply line-by-line by sequence.
            line = tpl.line_ids.sorted("sequence")[:1]
            if not line:
                continue
            rec.write(
                {
                    "authorization_role": line.role,
                    "authorization_service_ids": [(6, 0, line.service_ids.ids)],
                    "authorization_effective_months": line.effective_months,
                }
            )
            rec.message_post(
                body=_(
                    "Authorization settings loaded from template %(template)s (line role: %(role)s)."
                )
                % {"template": tpl.name, "role": line.role}
            )
        return True
