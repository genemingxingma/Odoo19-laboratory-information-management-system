from odoo import _, fields, models
from odoo.exceptions import UserError


class LabSampleReceiveWizard(models.TransientModel):
    _name = "lab.sample.receive.wizard"
    _description = "Lab Sample Receive Wizard"

    accession = fields.Char(required=True, string="Accession / Barcode")

    def action_receive_sample(self):
        self.ensure_one()
        code = (self.accession or "").strip()
        if not code:
            raise UserError(_("Please input accession/barcode."))

        sample = self.env["lab.sample"].search(
            ["|", ("name", "=", code), ("accession_barcode", "=", code)],
            limit=1,
        )
        if not sample:
            raise UserError(_("Sample not found: %s") % code)

        if sample.state == "cancel":
            raise UserError(_("Sample is cancelled and cannot be received."))

        if sample.state == "reported":
            raise UserError(_("Sample is already reported."))

        if sample.state in ("received", "in_progress", "to_verify", "verified"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Receive Sample"),
                    "message": _("Sample %s already received.") % sample.name,
                    "type": "warning",
                    "sticky": False,
                },
            }

        sample.action_receive()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Receive Sample"),
                "message": _("Sample %s received successfully.") % sample.name,
                "type": "success",
                "sticky": False,
            },
        }
