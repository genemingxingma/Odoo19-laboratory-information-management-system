from odoo import api, fields, models


class LabPhysicianDepartment(models.Model):
    _name = "lab.physician.department"
    _description = "Physician Department"
    _order = "sequence, name, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    _sql_constraints = [
        ("lab_physician_department_code_company_uniq", "unique(code, company_id)", "Department code must be unique per company."),
        ("lab_physician_department_name_company_uniq", "unique(name, company_id)", "Department name must be unique per company."),
    ]


class ResPartnerLabPhysician(models.Model):
    _inherit = "res.partner"

    is_lab_physician = fields.Boolean(string="Lab Physician", default=False, index=True)
    lab_physician_department_id = fields.Many2one(
        "lab.physician.department",
        string="Physician Department",
        domain="[('company_id', '=', lab_physician_company_id)]",
    )
    lab_physician_company_id = fields.Many2one(
        "res.company",
        string="Physician Company",
        default=lambda self: self.env.company,
        index=True,
    )

    @api.onchange("is_lab_physician")
    def _onchange_is_lab_physician(self):
        for rec in self:
            if not rec.is_lab_physician:
                rec.lab_physician_department_id = False

