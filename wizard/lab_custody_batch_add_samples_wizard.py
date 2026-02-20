from odoo import _, fields, models
from odoo.exceptions import UserError


class LabCustodyBatchAddSamplesWizard(models.TransientModel):
    _name = "lab.custody.batch.add.samples.wizard"
    _description = "Add Samples to Custody Batch"

    batch_id = fields.Many2one("lab.sample.custody.batch", required=True)
    sample_ids = fields.Many2many("lab.sample", string="Samples", required=True)
    use_batch_to_user = fields.Boolean(default=True)
    to_user_id = fields.Many2one("res.users", string="To Custodian")
    to_location = fields.Char(string="To Location")

    def action_apply(self):
        self.ensure_one()
        if self.batch_id.state != "draft":
            raise UserError(_("Only draft batch can add samples."))
        if not self.sample_ids:
            raise UserError(_("Please select at least one sample."))

        if self.use_batch_to_user:
            to_user = self.batch_id.to_user_id
            to_location = self.batch_id.to_location
        else:
            to_user = self.to_user_id or self.batch_id.to_user_id
            to_location = self.to_location or self.batch_id.to_location

        if not to_user:
            raise UserError(_("Target custodian is required."))

        existing_ids = set(self.batch_id.line_ids.mapped("sample_id").ids)
        to_create = []
        for sample in self.sample_ids:
            if sample.id in existing_ids:
                continue
            to_create.append(
                {
                    "batch_id": self.batch_id.id,
                    "sample_id": sample.id,
                    "from_user_id": sample.current_custodian_id.id,
                    "to_user_id": to_user.id,
                    "from_location": sample.custody_location,
                    "to_location": to_location,
                    "state": "draft",
                }
            )
        if not to_create:
            raise UserError(_("All selected samples already exist in batch."))

        self.env["lab.sample.custody.batch.line"].create(to_create)
        return {"type": "ir.actions.act_window_close"}
