from odoo import _, fields, models
from odoo.exceptions import UserError


class LabSampleTransferCustodyWizard(models.TransientModel):
    _name = "lab.sample.transfer.custody.wizard"
    _description = "Transfer Sample Custody Wizard"

    sample_id = fields.Many2one("lab.sample", required=True, readonly=True)
    from_user_id = fields.Many2one("res.users", string="Current Custodian", readonly=True)
    to_user_id = fields.Many2one("res.users", string="Transfer To", required=True)
    location = fields.Char(string="New Location")
    note = fields.Char(string="Transfer Note")

    def action_transfer(self):
        self.ensure_one()
        if not self.sample_id:
            raise UserError(_("No sample selected."))
        if self.to_user_id == self.from_user_id:
            raise UserError(_("Transfer target must be a different user."))
        self.sample_id._transfer_custody(self.to_user_id, self.location, self.note)
        return {"type": "ir.actions.act_window_close"}
