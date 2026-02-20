from odoo import _, fields, models
from odoo.exceptions import UserError


class LabCustodyInvestigationBulkUpdateWizard(models.TransientModel):
    _name = "lab.custody.investigation.bulk.update.wizard"
    _description = "Bulk Update Custody Investigation Wizard"

    investigation_ids = fields.Many2many(
        "lab.custody.investigation",
        "lab_cust_inv_bulk_rel",
        "wizard_id",
        "investigation_id",
        string="Investigations",
        required=True,
    )
    apply_owner = fields.Boolean(string="Update Owner", default=False)
    owner_id = fields.Many2one("res.users", string="New Owner")
    apply_state = fields.Boolean(string="Update State", default=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("open", "Open"),
            ("root_cause", "Root Cause"),
            ("capa", "CAPA"),
            ("verification", "Verification"),
            ("closed", "Closed"),
            ("cancel", "Cancelled"),
        ],
        string="Target State",
    )
    apply_target_date = fields.Boolean(string="Update Target Close Date", default=False)
    target_close_date = fields.Date(string="Target Close Date")
    apply_sla_policy = fields.Boolean(string="Apply SLA Policy", default=False)
    sla_policy_id = fields.Many2one("lab.custody.sla.policy", string="SLA Policy")
    add_internal_note = fields.Boolean(string="Post Internal Note", default=False)
    internal_note = fields.Text(string="Internal Note")

    def _prepare_investigations(self):
        self.ensure_one()
        inv_ids = self.env.context.get("active_ids")
        if inv_ids:
            return self.env["lab.custody.investigation"].browse(inv_ids).exists()
        return self.investigation_ids

    def action_apply(self):
        self.ensure_one()
        investigations = self._prepare_investigations()
        if not investigations:
            raise UserError(_("No investigations selected."))

        vals = {}
        if self.apply_owner:
            if not self.owner_id:
                raise UserError(_("Please select owner."))
            vals["owner_id"] = self.owner_id.id

        if self.apply_state:
            if not self.state:
                raise UserError(_("Please select state."))
            vals["state"] = self.state

        if self.apply_target_date:
            if not self.target_close_date:
                raise UserError(_("Please select target close date."))
            vals["target_close_date"] = self.target_close_date

        if self.apply_sla_policy:
            if not self.sla_policy_id:
                raise UserError(_("Please select SLA policy."))
            vals["sla_policy_id"] = self.sla_policy_id.id

        if vals:
            investigations.write(vals)
            if self.apply_sla_policy:
                investigations.action_recompute_sla()

        if self.add_internal_note and self.internal_note:
            for inv in investigations:
                inv.message_post(body=self.internal_note, subtype_xmlid="mail.mt_note")

        return {"type": "ir.actions.act_window_close"}
