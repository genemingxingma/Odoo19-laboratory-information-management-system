from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabMethodValidation(models.Model):
    _name = "lab.method.validation"
    _description = "Lab Method Validation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    service_id = fields.Many2one("lab.service", required=True, tracking=True)
    method_version = fields.Char(required=True, tracking=True)
    validation_type = fields.Selection(
        [
            ("verification", "Verification"),
            ("validation", "Validation"),
            ("revalidation", "Revalidation"),
        ],
        default="verification",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("expired", "Expired"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    plan_note = fields.Text(string="Validation Plan")
    precision_plan = fields.Text()
    accuracy_plan = fields.Text()
    linearity_plan = fields.Text()
    lod_loq_plan = fields.Text()
    reference_interval_plan = fields.Text()

    precision_result = fields.Text()
    accuracy_result = fields.Text()
    linearity_result = fields.Text()
    lod_loq_result = fields.Text()
    reference_interval_result = fields.Text()
    summary_result = fields.Text(string="Validation Summary")

    acceptance_criteria = fields.Text()
    overall_pass = fields.Boolean(default=False, tracking=True)

    effective_from = fields.Date()
    effective_to = fields.Date()
    review_interval_months = fields.Integer(default=12)
    next_review_date = fields.Date(compute="_compute_next_review_date", store=True)

    approved_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    approved_at = fields.Datetime(readonly=True, tracking=True)
    rejected_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    rejected_at = fields.Datetime(readonly=True, tracking=True)
    reject_reason = fields.Text()

    is_active_for_release = fields.Boolean(compute="_compute_is_active_for_release", store=True)

    _sql_constraints = [
        (
            "method_validation_unique_service_version",
            "unique(service_id, method_version)",
            "Method version must be unique per service.",
        )
    ]

    @api.depends("effective_from", "review_interval_months")
    def _compute_next_review_date(self):
        for rec in self:
            if rec.effective_from and rec.review_interval_months > 0:
                rec.next_review_date = fields.Date.add(rec.effective_from, months=rec.review_interval_months)
            else:
                rec.next_review_date = False

    @api.depends("state", "effective_from", "effective_to")
    def _compute_is_active_for_release(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_active_for_release = bool(
                rec.state == "approved"
                and (not rec.effective_from or rec.effective_from <= today)
                and (not rec.effective_to or rec.effective_to >= today)
            )

    @api.constrains("review_interval_months")
    def _check_review_interval(self):
        for rec in self:
            if rec.review_interval_months < 0:
                raise ValidationError(_("Review interval months must be non-negative."))

    @api.constrains("effective_from", "effective_to")
    def _check_effective_range(self):
        for rec in self:
            if rec.effective_from and rec.effective_to and rec.effective_to < rec.effective_from:
                raise ValidationError(_("Effective to date cannot be earlier than effective from date."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.method.validation") or "New"
        return super().create(vals_list)

    def action_start(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec.state = "in_progress"

    def action_submit(self):
        for rec in self:
            if rec.state not in ("draft", "in_progress", "rejected"):
                continue
            rec.state = "pending_approval"

    def action_approve(self):
        for rec in self:
            if rec.state != "pending_approval":
                continue
            if not rec.overall_pass:
                raise UserError(_("Only passed validation can be approved."))
            if not rec.effective_from:
                rec.effective_from = fields.Date.today()
            rec.write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                    "rejected_by_id": False,
                    "rejected_at": False,
                    "reject_reason": False,
                }
            )

    def action_reject(self):
        for rec in self:
            if rec.state not in ("pending_approval", "approved"):
                continue
            if not (rec.reject_reason or "").strip():
                raise UserError(_("Reject reason is required."))
            rec.write(
                {
                    "state": "rejected",
                    "rejected_by_id": self.env.user.id,
                    "rejected_at": fields.Datetime.now(),
                }
            )

    def action_expire(self):
        for rec in self:
            if rec.state != "approved":
                continue
            rec.state = "expired"

    @api.model
    def _cron_notify_validation_review_due(self):
        today = fields.Date.today()
        due = self.search(
            [
                ("state", "=", "approved"),
                ("next_review_date", "!=", False),
                ("next_review_date", "<=", fields.Date.add(today, days=14)),
            ],
            limit=200,
        )
        if not due:
            return

        group = self.env.ref("laboratory_management.group_lab_quality_manager", raise_if_not_found=False)
        users = group.user_ids if group and group.user_ids else self.env.user
        entries = []
        for rec in due:
            for user in users:
                entries.append(
                    {
                        "res_id": rec.id,
                        "user_id": user.id,
                        "summary": "Method validation review due",
                        "note": _("Validation %(name)s for %(service)s review is due on %(date)s.")
                        % {
                            "name": rec.name,
                            "service": rec.service_id.name,
                            "date": rec.next_review_date,
                        },
                    }
                )
        self.env["lab.activity.helper.mixin"].create_unique_todo_activities(
            model_name="lab.method.validation",
            entries=entries,
        )

    @api.model
    def _cron_expire_overdue_validations(self):
        today = fields.Date.today()
        overdue = self.search(
            [
                ("state", "=", "approved"),
                ("effective_to", "!=", False),
                ("effective_to", "<", today),
            ],
            limit=500,
        )
        if overdue:
            overdue.write({"state": "expired"})
