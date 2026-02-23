from odoo import api, fields, models


class LabResultUnit(models.Model):
    _name = "lab.result.unit"
    _description = "Laboratory Result Unit"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=False)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("lab_result_unit_code_uniq", "unique(code)", "Result unit code must be unique."),
    ]

    @api.model
    def get_or_create_by_name(self, unit_name):
        label = (unit_name or "").strip()
        if not label:
            return False
        rec = self.search([("name", "=", label), ("active", "=", True)], limit=1)
        if rec:
            return rec
        code = (
            label.lower()
            .replace("/", "_")
            .replace(" ", "_")
            .replace("-", "_")
            .replace("%", "percent")
        )
        if not code:
            code = "unit"
        base = code
        idx = 1
        while self.search_count([("code", "=", code)]):
            idx += 1
            code = f"{base}_{idx}"
        return self.create({"name": label, "code": code, "active": True})
