from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabServiceAuthorization(models.Model):
    _name = "lab.service.authorization"
    _description = "Laboratory Service Personnel Authorization"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "next_assessment_date asc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    user_id = fields.Many2one("res.users", required=True, index=True, tracking=True)
    role = fields.Selection(
        [
            ("analyst", "Analyst"),
            ("technical_reviewer", "Technical Reviewer"),
            ("medical_reviewer", "Medical Reviewer"),
        ],
        required=True,
        default="analyst",
        tracking=True,
    )
    service_id = fields.Many2one("lab.service", required=True, index=True, tracking=True)
    department = fields.Selection(related="service_id.department", store=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("suspended", "Suspended"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        required=True,
        default="draft",
        tracking=True,
    )
    effective_from = fields.Date(required=True, default=fields.Date.today, tracking=True)
    effective_to = fields.Date(tracking=True)
    assessment_date = fields.Date(default=fields.Date.today, tracking=True)
    assessment_score = fields.Float(tracking=True)
    assessment_note = fields.Text()
    review_interval_months = fields.Integer(default=12)
    next_assessment_date = fields.Date(compute="_compute_next_assessment_date", store=True)

    approved_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    approved_date = fields.Datetime(readonly=True, tracking=True)
    revoked_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    revoked_date = fields.Datetime(readonly=True, tracking=True)

    is_currently_authorized = fields.Boolean(compute="_compute_is_currently_authorized", store=True)
    is_due_soon = fields.Boolean(compute="_compute_is_due_soon", store=True)

    _unique_live_row = models.Constraint(
        "unique(user_id, service_id, role, state)",
        "Duplicate authorization in the same state is not allowed for the same user/service/role.",
    )

    @api.depends("assessment_date", "review_interval_months")
    def _compute_next_assessment_date(self):
        for rec in self:
            if not rec.assessment_date or rec.review_interval_months <= 0:
                rec.next_assessment_date = False
                continue
            rec.next_assessment_date = fields.Date.add(rec.assessment_date, months=rec.review_interval_months)

    @api.depends("state", "effective_from", "effective_to")
    def _compute_is_currently_authorized(self):
        today = fields.Date.today()
        for rec in self:
            if rec.state != "approved":
                rec.is_currently_authorized = False
                continue
            if rec.effective_from and rec.effective_from > today:
                rec.is_currently_authorized = False
                continue
            if rec.effective_to and rec.effective_to < today:
                rec.is_currently_authorized = False
                continue
            rec.is_currently_authorized = True

    @api.depends("next_assessment_date", "state")
    def _compute_is_due_soon(self):
        today = fields.Date.today()
        threshold = today + timedelta(days=30)
        for rec in self:
            rec.is_due_soon = bool(
                rec.state == "approved"
                and rec.next_assessment_date
                and today <= rec.next_assessment_date <= threshold
            )

    @api.constrains("review_interval_months")
    def _check_review_interval_months(self):
        for rec in self:
            if rec.review_interval_months < 0:
                raise UserError(_("Review interval months must be zero or positive."))

    @api.constrains("effective_from", "effective_to")
    def _check_effective_period(self):
        for rec in self:
            if rec.effective_from and rec.effective_to and rec.effective_to < rec.effective_from:
                raise UserError(_("Effective To must be on or after Effective From."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.service.authorization") or "New"
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state not in ("draft", "suspended"):
                continue
            rec.state = "pending"
            rec.message_post(body=_("Authorization submitted for approval."))
        return True

    def action_approve(self):
        for rec in self:
            if rec.state not in ("draft", "pending", "expired", "suspended"):
                continue
            rec.write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_date": fields.Datetime.now(),
                    "revoked_by_id": False,
                    "revoked_date": False,
                }
            )
            rec.message_post(body=_("Authorization approved."))
        return True

    def action_suspend(self):
        self.write({"state": "suspended"})
        return True

    def action_revoke(self):
        for rec in self:
            rec.write(
                {
                    "state": "revoked",
                    "revoked_by_id": self.env.user.id,
                    "revoked_date": fields.Datetime.now(),
                }
            )
            rec.message_post(body=_("Authorization revoked."))
        return True

    def action_mark_expired(self):
        self.write({"state": "expired"})
        return True

    def action_reset_draft(self):
        self.write({"state": "draft"})
        return True

    @api.model
    def _cron_expire_authorizations(self):
        today = fields.Date.today()
        rows = self.search(
            [
                ("state", "=", "approved"),
                ("effective_to", "!=", False),
                ("effective_to", "<", today),
            ]
        )
        if rows:
            rows.write({"state": "expired"})

    @api.model
    def _cron_notify_authorization_due(self):
        helper = self.env["lab.activity.helper.mixin"]
        reviewer_group = self.env.ref("laboratory_management.group_lab_quality_manager", raise_if_not_found=False)
        users = reviewer_group.user_ids if reviewer_group and reviewer_group.user_ids else self.env.user

        today = fields.Date.today()
        soon = today + timedelta(days=30)
        rows = self.search(
            [
                ("state", "=", "approved"),
                ("next_assessment_date", "!=", False),
                ("next_assessment_date", ">=", today),
                ("next_assessment_date", "<=", soon),
            ]
        )
        entries = []
        for rec in rows:
            days_to_due = (rec.next_assessment_date - today).days if rec.next_assessment_date else 30
            if days_to_due <= 7:
                tier = "D7"
                summary = "Personnel authorization reassessment due in 7 days"
            elif days_to_due <= 14:
                tier = "D14"
                summary = "Personnel authorization reassessment due in 14 days"
            else:
                tier = "D30"
                summary = "Personnel authorization reassessment due in 30 days"
            note = _(
                "[%(tier)s] Authorization %(name)s for %(user)s (%(service)s/%(role)s) needs reassessment before %(due)s."
            ) % {
                "tier": tier,
                "name": rec.name,
                "user": rec.user_id.name,
                "service": rec.service_id.name,
                "role": rec.role,
                "due": rec.next_assessment_date,
            }
            for user in users:
                entries.append(
                    {
                        "res_id": rec.id,
                        "user_id": user.id,
                        "summary": summary,
                        "note": note,
                    }
                )
        helper.create_unique_todo_activities(model_name="lab.service.authorization", entries=entries)
