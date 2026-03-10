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
    lab_default_report_template_id = fields.Many2one(
        "lab.report.template",
        string="Default Lab Report Template",
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help="When this partner is used as institution/client in a portal test request, the request uses this template by default.",
    )

    @api.onchange("is_lab_physician")
    def _onchange_is_lab_physician(self):
        for rec in self:
            if not rec.is_lab_physician:
                rec.lab_physician_department_id = False


class LabPhysician(models.Model):
    _name = "lab.physician"
    _description = "Laboratory Physician"
    _inherit = ["mail.thread", "lab.master.data.mixin"]
    _order = "name, id"

    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    name = fields.Char(required=True, tracking=True)
    code = fields.Char(string="Physician Code", tracking=True, index=True)
    license_no = fields.Char(string="License Number", tracking=True)
    title = fields.Char(string="Professional Title")
    specialty = fields.Char(string="Specialty")
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    institution_partner_id = fields.Many2one("res.partner", string="Institution", index=True)
    lab_physician_department_id = fields.Many2one(
        "lab.physician.department",
        string="Department",
        domain="[('company_id', '=', company_id)]",
    )
    signature_image = fields.Binary(string="Signature")
    notify_by_email = fields.Boolean(string="Notify by Email", default=True)
    notify_by_sms = fields.Boolean(string="Notify by SMS", default=False)
    note = fields.Text(string="Notes")
    partner_id = fields.Many2one("res.partner", string="Linked Contact", readonly=True, copy=False, index=True)

    request_ids = fields.One2many("lab.test.request", "physician_partner_id", string="Test Requests", readonly=True)

    _sql_constraints = [
        (
            "lab_physician_code_company_uniq",
            "unique(code, company_id)",
            "Physician code must be unique per company.",
        ),
        (
            "lab_physician_license_company_uniq",
            "unique(license_no, company_id)",
            "Physician license number must be unique per company.",
        ),
    ]
