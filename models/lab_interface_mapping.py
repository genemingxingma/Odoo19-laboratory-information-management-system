from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabInterfaceMappingProfile(models.Model):
    _name = "lab.interface.mapping.profile"
    _description = "Interface Mapping Profile"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    protocol = fields.Selection(
        [("hl7v2", "HL7 v2.x"), ("fhir", "FHIR R4"), ("astm", "ASTM"), ("rest", "REST/JSON"), ("sftp", "SFTP")],
        required=True,
        default="rest",
    )
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        required=True,
        default="outbound",
    )
    message_type = fields.Selection(
        [
            ("order", "Order Message"),
            ("result", "Result Message"),
            ("report", "Report Message"),
            ("ack", "ACK/NACK"),
            ("patient", "Patient Master"),
            ("qc", "QC Message"),
        ],
        required=True,
        default="order",
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("lab.interface.mapping.line", "profile_id", string="Rules")
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "Mapping profile code must be unique.")

    @staticmethod
    def _path_get(payload, path):
        if not path:
            return payload
        current = payload or {}
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    @staticmethod
    def _path_set(payload, path, value):
        if not path:
            return
        current = payload
        parts = path.split(".")
        for part in parts[:-1]:
            if part not in current or not isinstance(current.get(part), dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _transform_value(self, rec, value):
        if value in (None, False, "") and rec.default_value not in (None, False, ""):
            value = rec.default_value
        if rec.transform == "to_string" and value not in (None, False):
            return str(value)
        if rec.transform == "to_float" and value not in (None, False, ""):
            try:
                return float(value)
            except Exception:  # noqa: BLE001
                return value
        if rec.transform == "upper" and isinstance(value, str):
            return value.upper()
        if rec.transform == "lower" and isinstance(value, str):
            return value.lower()
        return value

    def map_payload(self, payload):
        self.ensure_one()
        result = {}
        for rec in self.line_ids.sorted("sequence"):
            value = self._path_get(payload, rec.source_path)
            value = self._transform_value(rec, value)
            if rec.required and value in (None, False, ""):
                raise ValidationError(_("Mapping required source path missing: %s") % rec.source_path)
            if value in (None, False, "") and not rec.required and rec.default_value in (None, False, ""):
                continue
            self._path_set(result, rec.target_path, value)
        return result or payload


class LabInterfaceMappingLine(models.Model):
    _name = "lab.interface.mapping.line"
    _description = "Interface Mapping Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    profile_id = fields.Many2one("lab.interface.mapping.profile", required=True, ondelete="cascade", index=True)
    source_path = fields.Char(required=True, help="Source JSON path, e.g. request_no or patient.name")
    target_path = fields.Char(required=True, help="Target JSON path")
    transform = fields.Selection(
        [
            ("as_is", "As Is"),
            ("to_string", "To String"),
            ("to_float", "To Float"),
            ("upper", "Upper"),
            ("lower", "Lower"),
        ],
        default="as_is",
        required=True,
    )
    default_value = fields.Char()
    required = fields.Boolean(default=False)
    note = fields.Char()

    _profile_source_target_uniq = models.Constraint(
        "unique(profile_id, source_path, target_path)",
        "Duplicate mapping rule.",
    )
