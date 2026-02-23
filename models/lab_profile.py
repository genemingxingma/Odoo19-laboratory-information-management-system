from odoo import fields, models


class LabProfile(models.Model):
    _name = "lab.profile"
    _description = "Analysis Panel"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("lab.profile.line", "profile_id", string="Panel Services")


class LabProfileLine(models.Model):
    _name = "lab.profile.line"
    _description = "Analysis Panel Line"

    profile_id = fields.Many2one("lab.profile", required=True, ondelete="cascade")
    service_id = fields.Many2one("lab.service", required=True)
