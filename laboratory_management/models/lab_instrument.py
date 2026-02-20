from odoo import fields, models


class LabInstrument(models.Model):
    _name = "lab.instrument"
    _description = "Lab Instrument"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
        default="chemistry",
        required=True,
    )
    active = fields.Boolean(default=True)
    mapping_ids = fields.One2many("lab.instrument.test.map", "instrument_id", string="Test Mapping")


class LabInstrumentTestMap(models.Model):
    _name = "lab.instrument.test.map"
    _description = "Instrument Test Mapping"

    instrument_id = fields.Many2one("lab.instrument", required=True, ondelete="cascade")
    instrument_test_code = fields.Char(required=True)
    service_id = fields.Many2one("lab.service", required=True)
