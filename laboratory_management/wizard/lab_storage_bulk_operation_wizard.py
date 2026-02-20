from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabStorageBulkOperationWizard(models.TransientModel):
    _name = "lab.storage.bulk.operation.wizard"
    _description = "Bulk Storage Operation Wizard"

    operation = fields.Selection(
        [
            ("store", "Store"),
            ("move", "Move"),
            ("retrieve", "Retrieve"),
            ("return", "Return to Storage"),
            ("dispose", "Dispose"),
        ],
        required=True,
        default="store",
    )
    sample_ids = fields.Many2many("lab.sample", string="Samples", required=True)
    storage_location_id = fields.Many2one("lab.storage.location", string="Storage Location")
    box = fields.Char(string="Storage Box")
    slot = fields.Char(string="Storage Slot")
    note = fields.Char(string="Operation Note")

    disposal_method = fields.Selection(
        [
            ("incineration", "Incineration"),
            ("biohazard", "Biohazard Waste"),
            ("vendor_return", "Return to Vendor"),
            ("other", "Other"),
        ],
        default="biohazard",
    )
    disposal_reason = fields.Char(string="Disposal Reason")
    witness_name = fields.Char(string="Witness")

    apply_only_reported = fields.Boolean(
        string="Only Apply on Verified/Reported Samples",
        default=True,
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        if active_ids and "sample_ids" in fields_list:
            res["sample_ids"] = [(6, 0, active_ids)]
        return res

    @api.model
    def action_open_wizard(self):
        return {
            "name": _("Bulk Storage Operation"),
            "type": "ir.actions.act_window",
            "res_model": "lab.storage.bulk.operation.wizard",
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context),
        }

    def _get_target_samples(self):
        self.ensure_one()
        samples = self.sample_ids
        if self.apply_only_reported:
            samples = samples.filtered(lambda s: s.state in ("verified", "reported", "to_verify", "in_progress"))
        return samples

    def action_apply(self):
        self.ensure_one()
        samples = self._get_target_samples()
        if not samples:
            raise UserError(_("No eligible samples found for selected operation."))

        if self.operation in ("store", "move") and not self.storage_location_id:
            raise UserError(_("Storage location is required for store/move operations."))
        if self.operation == "dispose" and not self.disposal_reason:
            raise UserError(_("Disposal reason is required."))

        processed = 0
        skipped = 0
        messages = []
        for sample in samples:
            try:
                if self.operation == "store":
                    sample._apply_store_sample(
                        location=self.storage_location_id,
                        box=self.box,
                        slot=self.slot,
                        note=self.note or _("Stored by bulk operation"),
                    )
                elif self.operation == "move":
                    sample._apply_store_sample(
                        location=self.storage_location_id,
                        box=self.box,
                        slot=self.slot,
                        note=self.note or _("Moved by bulk operation"),
                    )
                elif self.operation == "retrieve":
                    sample._apply_retrieve_sample(note=self.note or _("Retrieved by bulk operation"))
                elif self.operation == "return":
                    sample._apply_return_sample(note=self.note or _("Returned by bulk operation"))
                elif self.operation == "dispose":
                    sample._apply_dispose_sample(
                        method=self.disposal_method,
                        reason=self.disposal_reason,
                        witness_name=self.witness_name,
                        note=self.note or _("Disposed by bulk operation"),
                    )
                processed += 1
            except UserError as exc:
                skipped += 1
                messages.append(f"{sample.name}: {exc.args[0]}")

        result_msg = _("Processed: %(p)s, Skipped: %(s)s") % {"p": processed, "s": skipped}
        if messages:
            result_msg += "\n" + "\n".join(messages[:10])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Bulk Storage Operation"),
                "message": result_msg,
                "type": "success" if processed and not skipped else "warning",
                "sticky": bool(skipped),
            },
        }
