from odoo import fields, models


class LabPatient(models.Model):
    _name = "lab.patient"
    _description = "Laboratory Patient"
    _inherit = ["mail.thread", "lab.master.data.mixin"]
    _order = "name, id"

    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    name = fields.Char(required=True, tracking=True)
    identifier = fields.Char(string="Patient ID / Passport", tracking=True, index=True)
    birthdate = fields.Date(string="Date of Birth")
    gender = fields.Selection(
        [("male", "Male"), ("female", "Female"), ("other", "Other"), ("unknown", "Unknown")],
        default="unknown",
    )
    phone = fields.Char(string="Phone")
    email = fields.Char(string="Email")
    lang = fields.Selection(selection=lambda self: self.env["res.lang"].get_installed(), string="Language")
    street = fields.Char(string="Street")
    street2 = fields.Char(string="Street 2")
    city = fields.Char(string="City")
    state = fields.Char(string="State/Province")
    zip = fields.Char(string="ZIP")
    country = fields.Char(string="Country")

    emergency_contact_name = fields.Char(string="Emergency Contact Name")
    emergency_contact_phone = fields.Char(string="Emergency Contact Phone")
    emergency_contact_relation = fields.Char(string="Emergency Contact Relation")

    allergy_history = fields.Text(string="Allergy History")
    past_medical_history = fields.Text(string="Past Medical History")
    medication_history = fields.Text(string="Medication History")
    pregnancy_status = fields.Selection(
        [
            ("not_applicable", "Not Applicable"),
            ("pregnant", "Pregnant"),
            ("not_pregnant", "Not Pregnant"),
            ("unknown", "Unknown"),
        ],
        default="not_applicable",
    )
    breastfeeding = fields.Boolean(string="Breastfeeding")
    insurance_provider = fields.Char(string="Insurance Provider")
    insurance_no = fields.Char(string="Insurance Number")
    informed_consent_signed = fields.Boolean(string="Informed Consent Signed")
    informed_consent_date = fields.Date(string="Consent Date")
    note = fields.Text(string="Notes")
    partner_id = fields.Many2one("res.partner", string="Linked Contact", readonly=True, copy=False, index=True)

    request_ids = fields.One2many("lab.test.request", "patient_id", string="Test Requests", readonly=True)
    sample_ids = fields.One2many("lab.sample", "patient_id", string="Samples", readonly=True)

    _sql_constraints = [
        (
            "lab_patient_identifier_company_uniq",
            "unique(identifier, company_id)",
            "Patient identifier must be unique per company.",
        ),
    ]
