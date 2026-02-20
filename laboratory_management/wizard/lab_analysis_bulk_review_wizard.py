from odoo import _, api, fields, models


class LabAnalysisBulkReviewWizard(models.TransientModel):
    _name = "lab.analysis.bulk.review.wizard"
    _description = "Bulk Manual Review Wizard"

    analysis_ids = fields.Many2many("lab.sample.analysis", string="Analyses")
    decision = fields.Selection(
        [("verify", "Verify"), ("reject", "Reject")],
        default="verify",
        required=True,
    )
    reason_template_id = fields.Many2one("lab.review.reason.template", string="Review Template")
    reviewer_note = fields.Char(string="Reviewer Note")
    only_manual_review = fields.Boolean(default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get("active_ids") or []
        analysis_obj = self.env["lab.sample.analysis"]
        lines = analysis_obj.browse(active_ids).exists()
        if not lines:
            lines = analysis_obj.search(
                [
                    ("needs_manual_review", "=", True),
                    ("state", "in", ("assigned", "done")),
                ],
                limit=200,
            )
        if "analysis_ids" in fields_list:
            res["analysis_ids"] = [(6, 0, lines.ids)]
        return res

    @api.model
    def action_open_wizard(self):
        return {
            "name": _("Batch Manual Review"),
            "type": "ir.actions.act_window",
            "res_model": "lab.analysis.bulk.review.wizard",
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context),
        }

    def action_apply(self):
        self.ensure_one()
        lines = self.analysis_ids
        if self.only_manual_review:
            lines = lines.filtered(lambda x: x.needs_manual_review and x.state in ("assigned", "done"))

        template_note = self.reason_template_id.recommendation if self.reason_template_id else False
        extra_note = self.reviewer_note or False

        for line in lines:
            note = line.result_note or ""
            for snippet in [template_note, extra_note]:
                if snippet and snippet not in note:
                    note = (note + "\n" if note else "") + snippet
            if note != (line.result_note or ""):
                line.result_note = note

            if line.needs_manual_review and not line.review_assigned_user_id:
                line.action_claim_manual_review()

            if self.decision == "verify":
                line.action_verify_result()
            else:
                line.action_reject_result()

        return {"type": "ir.actions.act_window_close"}
