from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabSampleReviewLog(models.Model):
    _name = "lab.sample.review.log"
    _description = "Sample Dual Review Log"
    _order = "id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True)
    stage = fields.Selection(
        [
            ("technical", "Technical Review"),
            ("medical", "Medical Review"),
        ],
        required=True,
        index=True,
    )
    action = fields.Selection(
        [
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("reopened", "Reopened"),
        ],
        required=True,
        index=True,
    )
    user_id = fields.Many2one("res.users", required=True, index=True)
    note = fields.Text()
    event_time = fields.Datetime(default=fields.Datetime.now, required=True, index=True)


class LabSample(models.Model):
    _inherit = "lab.sample"

    technical_review_state = fields.Selection(
        [
            ("none", "No Review"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="none",
        readonly=True,
        tracking=True,
    )
    technical_reviewer_id = fields.Many2one("res.users", string="Technical Reviewer", readonly=True, tracking=True)
    technical_reviewed_at = fields.Datetime(string="Technical Reviewed At", readonly=True, tracking=True)
    technical_review_note = fields.Text(string="Technical Review Note")

    medical_review_state = fields.Selection(
        [
            ("none", "No Review"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="none",
        readonly=True,
        tracking=True,
    )
    medical_reviewer_id = fields.Many2one("res.users", string="Medical Reviewer", readonly=True, tracking=True)
    medical_reviewed_at = fields.Datetime(string="Medical Reviewed At", readonly=True, tracking=True)
    medical_review_note = fields.Text(string="Medical Review Note")

    review_required_for_release = fields.Boolean(
        compute="_compute_review_required_for_release",
        string="Dual Review Required",
    )
    review_release_ready = fields.Boolean(
        compute="_compute_review_release_ready",
        string="Review Release Ready",
    )
    review_block_reason = fields.Char(
        compute="_compute_review_release_ready",
        string="Review Block Reason",
    )
    review_log_ids = fields.One2many(
        "lab.sample.review.log",
        "sample_id",
        string="Dual Review Timeline",
        readonly=True,
    )

    dispatch_ids = fields.One2many("lab.report.dispatch", "sample_id", string="Report Dispatches", readonly=True)
    dispatch_count = fields.Integer(compute="_compute_dispatch_count")
    report_publication_state = fields.Selection(
        [
            ("active", "Active"),
            ("withdrawn", "Withdrawn"),
        ],
        default="active",
        required=True,
        tracking=True,
    )
    report_withdrawn_reason = fields.Text(string="Withdraw Reason")
    report_withdrawn_by_id = fields.Many2one("res.users", string="Withdrawn By", readonly=True, tracking=True)
    report_withdrawn_at = fields.Datetime(string="Withdrawn At", readonly=True, tracking=True)
    report_withdraw_input = fields.Text(string="Withdraw Input Reason")

    def _compute_dispatch_count(self):
        for rec in self:
            rec.dispatch_count = len(rec.dispatch_ids)

    def _is_report_public(self):
        self.ensure_one()
        return bool(self.state == "reported" and self.report_publication_state == "active")

    def action_view_dispatches(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_report_dispatch").sudo().read()[0]
        action["domain"] = [("sample_id", "=", self.id)]
        action["context"] = {
            "default_sample_id": self.id,
            "search_default_sample_id": self.id,
        }
        return action

    @api.depends_context("uid")
    def _compute_review_required_for_release(self):
        value = (self.env["ir.config_parameter"].sudo().get_param("laboratory_management.require_dual_review") or "1").strip()
        enabled = value not in ("0", "false", "False")
        for rec in self:
            rec.review_required_for_release = enabled

    @api.depends("technical_review_state", "medical_review_state", "state", "review_required_for_release")
    def _compute_review_release_ready(self):
        for rec in self:
            if not rec.review_required_for_release:
                rec.review_release_ready = rec.state == "verified"
                rec.review_block_reason = False
                continue

            if rec.technical_review_state != "approved":
                rec.review_release_ready = False
                rec.review_block_reason = _("Technical review is not approved.")
                continue

            if rec.medical_review_state != "approved":
                rec.review_release_ready = False
                rec.review_block_reason = _("Medical review is not approved.")
                continue

            rec.review_release_ready = rec.state == "verified"
            rec.review_block_reason = False if rec.review_release_ready else _("Sample is not in verified state.")

    def _create_review_log(self, stage, action, note=None):
        self.ensure_one()
        self.env["lab.sample.review.log"].sudo().create(
            {
                "sample_id": self.id,
                "stage": stage,
                "action": action,
                "user_id": self.env.user.id,
                "note": note or False,
                "event_time": fields.Datetime.now(),
            }
        )

    def _review_activity_key(self, stage):
        return "Dual Review: %s" % stage

    def _create_review_activity(self, stage):
        if stage == "technical":
            group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
            note_tpl = _("Technical review is required for sample %s.")
        else:
            group = self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
            note_tpl = _("Medical review is required for sample %s.")

        users = group.user_ids if group else self.env.user
        activity_type = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("lab.sample")
        summary = self._review_activity_key(stage)

        for rec in self:
            for user in users:
                exists = self.env["mail.activity"].search_count(
                    [
                        ("res_model_id", "=", model_id),
                        ("res_id", "=", rec.id),
                        ("user_id", "=", user.id),
                        ("summary", "=", summary),
                    ]
                )
                if exists:
                    continue
                self.env["mail.activity"].create(
                    {
                        "activity_type_id": activity_type.id,
                        "user_id": user.id,
                        "res_model_id": model_id,
                        "res_id": rec.id,
                        "summary": summary,
                        "note": note_tpl % rec.name,
                    }
                )

    def _close_review_activity(self, stage):
        model_id = self.env["ir.model"]._get_id("lab.sample")
        summary = self._review_activity_key(stage)
        activities = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", self.ids),
                ("summary", "=", summary),
            ]
        )
        if activities:
            activities.action_feedback(feedback=_("Review step completed."))

    def _set_review_pending(self, stage, note=None):
        now = fields.Datetime.now()
        for rec in self:
            if stage == "technical":
                rec.write(
                    {
                        "technical_review_state": "pending",
                        "technical_reviewer_id": False,
                        "technical_reviewed_at": False,
                        "technical_review_note": note if note is not None else rec.technical_review_note,
                    }
                )
            else:
                rec.write(
                    {
                        "medical_review_state": "pending",
                        "medical_reviewer_id": False,
                        "medical_reviewed_at": False,
                        "medical_review_note": note if note is not None else rec.medical_review_note,
                    }
                )
            rec._create_review_log(stage=stage, action="pending", note=note)
            rec._create_review_activity(stage)
            rec.message_post(body=_("%s review moved to pending.") % (stage.title()))

    def action_request_dual_review(self):
        for rec in self:
            if rec.state not in ("to_verify", "verified"):
                raise UserError(_("Dual review can be requested only after analysis verification stage."))
            rec._set_review_pending("technical")
            rec._set_review_pending("medical")
        return True

    def action_approve_technical_review(self):
        for rec in self:
            if rec.state not in ("verified", "reported"):
                raise UserError(_("Technical review can only be approved for verified/reported samples."))
            rec.write(
                {
                    "technical_review_state": "approved",
                    "technical_reviewer_id": self.env.user.id,
                    "technical_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_review_log("technical", "approved", rec.technical_review_note)
            rec._close_review_activity("technical")
            rec.message_post(body=_("Technical review approved."))
        return True

    def action_reject_technical_review(self):
        for rec in self:
            note = (rec.technical_review_note or "").strip()
            if not note:
                raise UserError(_("Technical rejection requires Technical Review Note."))
            rec.write(
                {
                    "technical_review_state": "rejected",
                    "technical_reviewer_id": self.env.user.id,
                    "technical_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_review_log("technical", "rejected", note)
            rec._close_review_activity("technical")
            rec.message_post(body=_("Technical review rejected."))
        return True

    def action_reopen_technical_review(self):
        for rec in self:
            rec.write(
                {
                    "technical_review_state": "pending",
                    "technical_reviewer_id": False,
                    "technical_reviewed_at": False,
                }
            )
            rec._create_review_log("technical", "reopened", rec.technical_review_note)
            rec._create_review_activity("technical")
            rec.message_post(body=_("Technical review reopened."))
        return True

    def action_approve_medical_review(self):
        for rec in self:
            if rec.state not in ("verified", "reported"):
                raise UserError(_("Medical review can only be approved for verified/reported samples."))
            rec.write(
                {
                    "medical_review_state": "approved",
                    "medical_reviewer_id": self.env.user.id,
                    "medical_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_review_log("medical", "approved", rec.medical_review_note)
            rec._close_review_activity("medical")
            rec.message_post(body=_("Medical review approved."))
        return True

    def action_reject_medical_review(self):
        for rec in self:
            note = (rec.medical_review_note or "").strip()
            if not note:
                raise UserError(_("Medical rejection requires Medical Review Note."))
            rec.write(
                {
                    "medical_review_state": "rejected",
                    "medical_reviewer_id": self.env.user.id,
                    "medical_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_review_log("medical", "rejected", note)
            rec._close_review_activity("medical")
            rec.message_post(body=_("Medical review rejected."))
        return True

    def action_reopen_medical_review(self):
        for rec in self:
            rec.write(
                {
                    "medical_review_state": "pending",
                    "medical_reviewer_id": False,
                    "medical_reviewed_at": False,
                }
            )
            rec._create_review_log("medical", "reopened", rec.medical_review_note)
            rec._create_review_activity("medical")
            rec.message_post(body=_("Medical review reopened."))
        return True

    def action_verify(self):
        result = super().action_verify()
        required = self.filtered(lambda s: s.review_required_for_release)
        if required:
            required._set_review_pending("technical")
            required._set_review_pending("medical")
        return result

    def _create_default_dispatches(self):
        dispatch_obj = self.env["lab.report.dispatch"]
        for rec in self:
            partners = rec.patient_id | rec.client_id
            partners = partners.filtered(lambda p: p)
            if not partners:
                continue
            for partner in partners:
                exists = dispatch_obj.search_count(
                    [
                        ("sample_id", "=", rec.id),
                        ("partner_id", "=", partner.id),
                        ("state", "!=", "cancel"),
                    ]
                )
                if exists:
                    continue
                dispatch_obj.create(
                    {
                        "sample_id": rec.id,
                        "partner_id": partner.id,
                        "channel": "portal",
                    }
                )

    def action_release_report(self):
        for rec in self:
            if rec.review_required_for_release and not rec.review_release_ready:
                raise UserError(rec.review_block_reason or _("Dual review is not complete."))
        result = super().action_release_report()
        self.write(
            {
                "report_publication_state": "active",
                "report_withdrawn_reason": False,
                "report_withdrawn_by_id": False,
                "report_withdrawn_at": False,
                "report_withdraw_input": False,
            }
        )
        self._create_default_dispatches()
        self.dispatch_ids.filtered(lambda d: d.state == "draft").action_mark_sent()
        return result

    def action_withdraw_report(self):
        for rec in self:
            if rec.state != "reported":
                raise UserError(_("Only reported sample can be withdrawn."))
            if rec.report_publication_state == "withdrawn":
                continue
            reason = (rec.report_withdraw_input or "").strip()
            if not reason:
                raise UserError(_("Withdrawal reason is required."))
            rec.write(
                {
                    "report_publication_state": "withdrawn",
                    "report_withdrawn_reason": reason,
                    "report_withdrawn_by_id": self.env.user.id,
                    "report_withdrawn_at": fields.Datetime.now(),
                }
            )
            rec.dispatch_ids.filtered(lambda d: d.state != "cancel").action_cancel_dispatch()
            if hasattr(rec, "_log_timeline"):
                rec._log_timeline("amendment", _("Report withdrawn from public access."))
            if hasattr(rec, "_create_signoff"):
                rec._create_signoff("amend", _("Report withdrawn"))
            rec.message_post(body=_("Report withdrawn. Reason: %s") % reason)
        return True

    def action_reissue_report(self):
        for rec in self:
            if rec.report_publication_state != "withdrawn":
                raise UserError(_("Only withdrawn reports can be reissued."))
            rec.write(
                {
                    "state": "verified",
                    "report_publication_state": "active",
                    "report_revision": rec.report_revision + 1,
                    "is_amended": True,
                    "report_withdraw_input": False,
                }
            )
            rec._set_review_pending("technical")
            rec._set_review_pending("medical")
            if hasattr(rec, "_log_timeline"):
                rec._log_timeline("amendment", _("Report reissued request created, pending release."))
            if hasattr(rec, "_create_signoff"):
                rec._create_signoff("amend", _("Report reissue initiated"))
            rec.message_post(body=_("Report reissue initiated. Please complete reviews and release again."))
        return True

    def action_print_report(self):
        for rec in self:
            if rec.state == "reported" and rec.report_publication_state == "withdrawn":
                raise UserError(_("Withdrawn report cannot be printed for external release."))
        return super().action_print_report()
