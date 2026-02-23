import base64
import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabTestRequestAttachmentWizard(models.TransientModel):
    _name = "lab.test.request.attachment.wizard"
    _description = "Upload Test Request Attachments"

    request_id = fields.Many2one("lab.test.request", required=True, readonly=True)
    line_ids = fields.One2many("lab.test.request.attachment.wizard.line", "wizard_id", string="Files")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get("request_id"):
            return res
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "lab.test.request" and active_id:
            res["request_id"] = active_id
        return res

    def action_upload(self):
        self.ensure_one()
        if not self.request_id:
            raise UserError(_("Please select a test request first."))
        payloads = []
        for line in self.line_ids:
            if not line.file_data:
                continue
            payloads.append(
                {
                    "name": line.name,
                    "content": base64.b64decode(line.file_data),
                    "mimetype": line.mimetype or "application/octet-stream",
                }
            )
        if not payloads:
            raise UserError(_("Please add at least one attachment file."))
        self.request_id._create_request_attachments(payloads, source="internal workbench")
        return {"type": "ir.actions.act_window_close"}


class LabTestRequestAttachmentWizardLine(models.TransientModel):
    _name = "lab.test.request.attachment.wizard.line"
    _description = "Upload Test Request Attachment Line"

    wizard_id = fields.Many2one("lab.test.request.attachment.wizard", required=True, ondelete="cascade")
    name = fields.Char(string="Filename", required=True)
    file_data = fields.Binary(string="File", required=True, attachment=False)
    mimetype = fields.Char(string="MIME Type")

    @api.onchange("name")
    def _onchange_name_guess_mimetype(self):
        for rec in self:
            if rec.name and not rec.mimetype:
                rec.mimetype = mimetypes.guess_type(rec.name)[0] or "application/octet-stream"
