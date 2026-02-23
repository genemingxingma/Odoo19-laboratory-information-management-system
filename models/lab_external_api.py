import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabInterfaceEndpointExternalApi(models.Model):
    _inherit = "lab.interface.endpoint"

    external_api_enabled = fields.Boolean(
        string="Enable External Lab API",
        default=False,
        help="Allow external institutions to push requests and query results/reports via API.",
    )
    external_partner_id = fields.Many2one(
        "res.partner",
        string="External Institution",
        help="Institution/commercial partner used for API data scoping.",
    )
    external_company_id = fields.Many2one(
        "res.company",
        string="Data Company",
        default=lambda self: self.env.company,
        required=True,
    )
    external_allow_request_push = fields.Boolean(string="Allow Request Push", default=True)
    external_allow_result_query = fields.Boolean(string="Allow Result Query", default=True)
    external_allow_report_download = fields.Boolean(string="Allow Report Download", default=True)
    external_allow_metadata_query = fields.Boolean(
        string="Allow Metadata Query",
        default=True,
        help="Allow external clients to query sample types, services, and profiles metadata.",
    )
    external_auto_submit_request = fields.Boolean(
        string="Auto Submit New Request",
        default=True,
        help="Automatically move new API requests to Submitted state.",
    )

    @api.constrains("external_api_enabled", "auth_type", "external_partner_id")
    def _check_external_api_settings(self):
        for rec in self:
            if not rec.external_api_enabled:
                continue
            if rec.auth_type == "none":
                raise ValidationError(_("External API endpoint cannot use 'None' authentication."))
            if not rec.external_partner_id:
                raise ValidationError(_("External API endpoint must select an External Institution."))

    def get_external_api_partner(self):
        self.ensure_one()
        if self.external_partner_id:
            return self.external_partner_id.commercial_partner_id
        schema = {}
        try:
            schema = json.loads(self.mapping_schema or "{}")
        except Exception:  # noqa: BLE001
            schema = {}
        partner_id = schema.get("external_partner_id") or schema.get("requester_partner_id")
        if partner_id:
            return self.env["res.partner"].sudo().browse(int(partner_id)).commercial_partner_id
        return self.env["res.partner"]


class LabTestRequestExternalApi(models.Model):
    _inherit = "lab.test.request"

    external_endpoint_id = fields.Many2one(
        "lab.interface.endpoint",
        string="External API Endpoint",
        readonly=True,
        copy=False,
        index=True,
    )
    external_request_uid = fields.Char(string="External Request UID", copy=False, index=True)

    _external_request_uid_uniq = models.Constraint(
        "unique(external_endpoint_id, external_request_uid)",
        "External Request UID must be unique per endpoint.",
    )

    def _check_external_write_state(self):
        for rec in self:
            if rec.external_endpoint_id and rec.state in ("completed", "cancelled"):
                raise ValidationError(_("Cannot overwrite completed/cancelled external request."))
