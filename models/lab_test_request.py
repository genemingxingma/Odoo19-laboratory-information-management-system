from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabTestRequest(models.Model):
    _name = "lab.test.request"
    _description = "Laboratory Test Request"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request No.", default="New", readonly=True, copy=False, tracking=True)
    requester_partner_id = fields.Many2one(
        "res.partner",
        string="Requester",
        default=lambda self: self.env.user.partner_id,
        required=True,
        tracking=True,
    )
    request_type = fields.Selection(
        [("individual", "Individual"), ("institution", "Institution")],
        default="individual",
        required=True,
        tracking=True,
    )
    client_partner_id = fields.Many2one("res.partner", string="Institution / Client", tracking=True)
    patient_id = fields.Many2one("res.partner", string="Existing Patient", tracking=True)
    patient_name = fields.Char(string="Patient Name", tracking=True)
    patient_identifier = fields.Char(string="Patient ID / Passport")
    patient_birthdate = fields.Date(string="Date of Birth")
    patient_gender = fields.Selection(
        [("male", "Male"), ("female", "Female"), ("other", "Other"), ("unknown", "Unknown")],
        default="unknown",
    )
    patient_phone = fields.Char(string="Patient Phone")

    physician_name = fields.Char(string="Physician")
    requested_collection_date = fields.Datetime(
        string="Requested Collection Time",
        default=fields.Datetime.now,
        tracking=True,
    )
    preferred_template_id = fields.Many2one("lab.report.template", string="Preferred Report Template")
    priority = fields.Selection(
        [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        default="routine",
        required=True,
        tracking=True,
    )
    sample_type = fields.Selection(
        [
            ("blood", "Blood"),
            ("urine", "Urine"),
            ("stool", "Stool"),
            ("swab", "Swab"),
            ("serum", "Serum"),
            ("other", "Other"),
        ],
        default="blood",
        required=True,
    )
    fasting_required = fields.Boolean(default=False)
    clinical_note = fields.Text(string="Clinical Note")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("triage", "In Triage"),
            ("quoted", "Quoted"),
            ("approved", "Approved"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )

    line_ids = fields.One2many("lab.test.request.line", "request_id", string="Requested Tests")
    timeline_ids = fields.One2many("lab.test.request.timeline", "request_id", string="Timeline", readonly=True)
    quote_revision_ids = fields.One2many(
        "lab.test.request.quote.revision", "request_id", string="Quote Revisions", readonly=True
    )
    sample_ids = fields.One2many("lab.sample", "request_id", string="Generated Samples", readonly=True)
    sample_count = fields.Integer(compute="_compute_sample_count")
    quote_revision_count = fields.Integer(compute="_compute_quote_revision_count")

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    amount_untaxed = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_discount = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_total = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)

    quote_reference = fields.Char(string="Quote Reference")
    quote_valid_until = fields.Date(string="Quote Valid Until")
    quote_note = fields.Text(string="Quote Note")
    quote_expired = fields.Boolean(compute="_compute_quote_expiry", search="_search_quote_expiry")
    quote_days_left = fields.Integer(compute="_compute_quote_expiry")
    quote_last_sent_at = fields.Datetime(readonly=True)
    quote_last_sent_by_id = fields.Many2one("res.users", readonly=True)
    quote_auto_reminder_count = fields.Integer(default=0, readonly=True)

    submitted_at = fields.Datetime(readonly=True)
    submitted_by_id = fields.Many2one("res.users", readonly=True)
    triaged_at = fields.Datetime(readonly=True)
    triaged_by_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approved_by_id = fields.Many2one("res.users", readonly=True)
    rejected_at = fields.Datetime(readonly=True)
    rejected_by_id = fields.Many2one("res.users", readonly=True)
    completed_at = fields.Datetime(readonly=True)

    rejection_reason = fields.Text()
    cancel_reason = fields.Text()

    estimated_turnaround_hours = fields.Integer(compute="_compute_tat", store=True)
    estimated_report_date = fields.Datetime(compute="_compute_tat", store=True)

    @api.depends("sample_ids")
    def _compute_sample_count(self):
        for rec in self:
            rec.sample_count = len(rec.sample_ids)

    @api.depends("quote_revision_ids")
    def _compute_quote_revision_count(self):
        for rec in self:
            rec.quote_revision_count = len(rec.quote_revision_ids)

    @api.depends("quote_valid_until", "state")
    def _compute_quote_expiry(self):
        today = fields.Date.today()
        for rec in self:
            if rec.state not in ("quoted", "submitted", "triage"):
                rec.quote_expired = False
                rec.quote_days_left = 0
                continue
            if not rec.quote_valid_until:
                rec.quote_expired = False
                rec.quote_days_left = 9999
                continue
            days_left = (rec.quote_valid_until - today).days
            rec.quote_days_left = days_left
            rec.quote_expired = days_left < 0

    def _search_quote_expiry(self, operator, value):
        today = fields.Date.today()
        expired_domain = [
            ("state", "in", ("quoted", "submitted", "triage")),
            ("quote_valid_until", "!=", False),
            ("quote_valid_until", "<", today),
        ]
        not_expired_domain = [
            "|",
            ("state", "not in", ("quoted", "submitted", "triage")),
            "|",
            ("quote_valid_until", "=", False),
            ("quote_valid_until", ">=", today),
        ]
        if operator in ("=", "=="):
            return expired_domain if value else not_expired_domain
        if operator == "!=":
            return not_expired_domain if value else expired_domain
        return expired_domain

    @api.depends("line_ids.subtotal", "line_ids.discount_amount")
    def _compute_amounts(self):
        for rec in self:
            untaxed = sum(rec.line_ids.mapped("subtotal"))
            discount = sum(rec.line_ids.mapped("discount_amount"))
            rec.amount_untaxed = untaxed + discount
            rec.amount_discount = discount
            rec.amount_total = untaxed

    @api.depends("line_ids", "line_ids.service_id.turnaround_hours", "requested_collection_date")
    def _compute_tat(self):
        for rec in self:
            tat = 0
            if rec.line_ids:
                tat = max(rec.line_ids.mapped("effective_turnaround_hours") or [0])
            rec.estimated_turnaround_hours = tat
            base_time = rec.requested_collection_date or fields.Datetime.now()
            rec.estimated_report_date = fields.Datetime.add(base_time, hours=tat) if tat else base_time

    @api.constrains("request_type", "client_partner_id")
    def _check_request_type(self):
        for rec in self:
            if rec.request_type == "institution" and not rec.client_partner_id:
                raise ValidationError(_("Institution request must select Institution / Client."))

    @api.constrains("line_ids")
    def _check_lines(self):
        for rec in self:
            if rec.state not in ("draft", "cancelled") and not rec.line_ids:
                raise ValidationError(_("At least one requested test is required."))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.test.request") or "New"
        records = super().create(vals_list)
        for rec in records:
            rec._log_timeline("draft", _("Request created"))
        return records

    def copy(self, default=None):
        default = dict(default or {})
        default["name"] = "New"
        default["state"] = "draft"
        default["sample_ids"] = [(5, 0, 0)]
        default["timeline_ids"] = [(5, 0, 0)]
        return super().copy(default)

    def _ensure_lines(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Please add at least one test item."))

    def action_submit(self):
        self._ensure_lines()
        for rec in self:
            if rec.state not in ("draft", "cancelled"):
                continue
            rec.write(
                {
                    "state": "submitted",
                    "submitted_at": fields.Datetime.now(),
                    "submitted_by_id": self.env.user.id,
                    "cancel_reason": False,
                }
            )
            rec._log_timeline("submitted", _("Request submitted"))
            rec._create_triage_activity()

    def action_start_triage(self):
        for rec in self:
            if rec.state not in ("submitted", "draft"):
                continue
            rec.write(
                {
                    "state": "triage",
                    "triaged_at": fields.Datetime.now(),
                    "triaged_by_id": self.env.user.id,
                }
            )
            rec._log_timeline("triage", _("Triage started"))

    def action_prepare_quote(self):
        self._ensure_lines()
        for rec in self:
            if rec.state not in ("submitted", "triage", "draft"):
                continue
            values = {
                "state": "quoted",
                "quote_reference": rec.quote_reference or rec.name,
            }
            if not rec.quote_valid_until:
                values["quote_valid_until"] = fields.Date.add(fields.Date.today(), days=7)
            rec.write(values)
            rec._create_quote_revision(reason=_("Initial quote preparation"))
            rec._log_timeline("quoted", _("Quote prepared"))
            rec._close_triage_activity()

    def action_send_quote(self):
        for rec in self:
            if rec.state != "quoted":
                raise UserError(_("Only quoted requests can send quote to requester."))
            rec.write(
                {
                    "quote_last_sent_at": fields.Datetime.now(),
                    "quote_last_sent_by_id": self.env.user.id,
                }
            )
            rec._log_timeline("quoted", _("Quote sent to requester"))
            rec.message_post(
                body=_("Quote %(quote)s sent to %(partner)s.")
                % {
                    "quote": rec.quote_reference or rec.name,
                    "partner": rec.requester_partner_id.name,
                },
                subtype_xmlid="mail.mt_note",
            )

    def action_create_quote_revision(self):
        for rec in self:
            if rec.state != "quoted":
                raise UserError(_("Quote revision can only be created in Quoted state."))
            rec._create_quote_revision(reason=_("Manual quote revision"))

    def _create_quote_revision(self, reason=False):
        self.ensure_one()
        revision_no = len(self.quote_revision_ids) + 1
        self.env["lab.test.request.quote.revision"].create(
            {
                "request_id": self.id,
                "revision_no": revision_no,
                "amount_untaxed": self.amount_untaxed,
                "amount_discount": self.amount_discount,
                "amount_total": self.amount_total,
                "quote_valid_until": self.quote_valid_until,
                "quote_note": self.quote_note,
                "reason": reason or _("Quote revision"),
                "created_by_id": self.env.user.id,
            }
        )

    def action_approve_quote(self):
        for rec in self:
            if rec.state != "quoted":
                raise UserError(_("Only quoted requests can be approved."))
            rec.write(
                {
                    "state": "approved",
                    "approved_at": fields.Datetime.now(),
                    "approved_by_id": self.env.user.id,
                    "rejection_reason": False,
                }
            )
            rec._log_timeline("approved", _("Quote approved"))
            rec._create_sample_creation_activity()

    def action_reject(self):
        for rec in self:
            if rec.state in ("completed", "cancelled"):
                continue
            rec.write(
                {
                    "state": "rejected",
                    "rejected_at": fields.Datetime.now(),
                    "rejected_by_id": self.env.user.id,
                }
            )
            rec._log_timeline("rejected", _("Request rejected"))
            rec._close_triage_activity()

    def action_cancel(self):
        for rec in self:
            if rec.state == "completed":
                raise UserError(_("Completed requests cannot be cancelled."))
            rec.state = "cancelled"
            rec._log_timeline("cancelled", _("Request cancelled"))
            rec._close_triage_activity()

    def action_reset_draft(self):
        for rec in self:
            if rec.state == "completed":
                raise UserError(_("Completed requests cannot be reset to draft."))
            rec.state = "draft"
            rec._log_timeline("draft", _("Request reset to draft"))

    def action_mark_completed(self):
        for rec in self:
            if rec.state not in ("approved", "in_progress"):
                continue
            rec.write({"state": "completed", "completed_at": fields.Datetime.now()})
            rec._log_timeline("completed", _("Request completed"))

    def action_open_portal(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": self.get_portal_url(),
            "target": "new",
        }

    def action_view_quote_revisions(self):
        self.ensure_one()
        return {
            "name": _("Quote Revisions"),
            "type": "ir.actions.act_window",
            "res_model": "lab.test.request.quote.revision",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_view_samples(self):
        self.ensure_one()
        return {
            "name": _("Generated Samples"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def _prepare_patient_partner(self):
        self.ensure_one()
        if self.patient_id:
            return self.patient_id

        name = (self.patient_name or "").strip()
        if not name:
            name = _("Unnamed Patient")

        commercial_partner = self.client_partner_id.commercial_partner_id if self.client_partner_id else False
        partner_vals = {
            "name": name,
            "phone": self.patient_phone,
            "is_company": False,
            "parent_id": commercial_partner.id if commercial_partner else False,
            "type": "contact",
            "comment": self.patient_identifier or False,
        }
        partner = self.env["res.partner"].create(partner_vals)
        self.patient_id = partner.id
        return partner

    def _expanded_service_payloads(self):
        self.ensure_one()
        payloads = []
        for line in self.line_ids:
            for payload in line.expand_to_services():
                payloads.append(payload)
        if not payloads:
            raise UserError(_("No analysis services found in request lines."))
        return payloads

    def action_create_samples(self):
        sample_model = self.env["lab.sample"]
        for rec in self:
            if rec.state not in ("approved", "in_progress"):
                raise UserError(_("Only approved requests can create samples."))

            patient = rec._prepare_patient_partner()
            payloads = rec._expanded_service_payloads()

            sample_vals = {
                "patient_id": patient.id,
                "client_id": rec.client_partner_id.id or rec.requester_partner_id.commercial_partner_id.id,
                "physician_name": rec.physician_name,
                "priority": rec.priority,
                "collection_date": rec.requested_collection_date,
                "report_template_id": rec.preferred_template_id.id,
                "note": rec.clinical_note,
                "request_id": rec.id,
                "analysis_ids": [
                    (
                        0,
                        0,
                        {
                            "service_id": p["service_id"],
                            "state": "pending",
                            "result_note": p.get("result_note"),
                        },
                    )
                    for p in payloads
                ],
            }
            sample = sample_model.create(sample_vals)
            rec.write({"state": "in_progress"})
            rec._log_timeline("sample_created", _("Sample %(sample)s created") % {"sample": sample.name})
            rec._close_sample_creation_activity()
            rec.message_post(
                body=_("Generated sample <b>%(sample)s</b> from request.") % {"sample": sample.name},
                subtype_xmlid="mail.mt_note",
            )
        return True

    def _create_triage_activity(self):
        triage_group = self.env.ref("laboratory_management.group_lab_reception", raise_if_not_found=False)
        users = triage_group.user_ids if triage_group and triage_group.user_ids else self.env.user
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self:
            for user in users:
                entries.append(
                    {
                        "res_id": rec.id,
                        "user_id": user.id,
                        "summary": "Triage test request",
                        "note": _("Please review request %(name)s and prepare quote.") % {"name": rec.name},
                    }
                )
        helper.create_unique_todo_activities(model_name="lab.test.request", entries=entries)

    def _close_triage_activity(self):
        model_id = self.env["ir.model"]._get_id("lab.test.request")
        activities = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", self.ids),
                ("summary", "=", "Triage test request"),
            ]
        )
        activities.action_done()

    def _create_sample_creation_activity(self):
        reception_group = self.env.ref("laboratory_management.group_lab_reception", raise_if_not_found=False)
        users = reception_group.user_ids if reception_group and reception_group.user_ids else self.env.user
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self:
            for user in users:
                entries.append(
                    {
                        "res_id": rec.id,
                        "user_id": user.id,
                        "summary": "Create accession from request",
                        "note": _("Request %(name)s is approved. Please create sample accession.") % {"name": rec.name},
                    }
                )
        helper.create_unique_todo_activities(model_name="lab.test.request", entries=entries)

    def _close_sample_creation_activity(self):
        model_id = self.env["ir.model"]._get_id("lab.test.request")
        activities = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", self.ids),
                ("summary", "=", "Create accession from request"),
            ]
        )
        activities.action_done()

    def _log_timeline(self, event_type, note):
        self.ensure_one()
        self.env["lab.test.request.timeline"].create(
            {
                "request_id": self.id,
                "event_type": event_type,
                "note": note,
                "event_time": fields.Datetime.now(),
                "user_id": self.env.user.id,
            }
        )

    @api.model
    def _cron_quote_expiry_followup(self):
        today = fields.Date.today()
        soon_expiring = self.search(
            [
                ("state", "=", "quoted"),
                ("quote_valid_until", "!=", False),
                ("quote_valid_until", ">=", today),
                ("quote_valid_until", "<=", fields.Date.add(today, days=2)),
            ]
        )
        expired = self.search(
            [
                ("state", "=", "quoted"),
                ("quote_valid_until", "!=", False),
                ("quote_valid_until", "<", today),
            ]
        )

        for rec in soon_expiring:
            rec.write({"quote_auto_reminder_count": rec.quote_auto_reminder_count + 1})
            rec.message_post(
                body=_(
                    "Quote %(quote)s will expire on %(date)s. Reminder #%(count)s generated automatically."
                )
                % {
                    "quote": rec.quote_reference or rec.name,
                    "date": rec.quote_valid_until,
                    "count": rec.quote_auto_reminder_count,
                },
                subtype_xmlid="mail.mt_note",
            )

        for rec in expired:
            rec.message_post(
                body=_("Quote %(quote)s has expired.") % {"quote": rec.quote_reference or rec.name},
                subtype_xmlid="mail.mt_note",
            )


class LabTestRequestLine(models.Model):
    _name = "lab.test.request.line"
    _description = "Laboratory Test Request Line"
    _order = "sequence, id"

    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    line_type = fields.Selection(
        [("service", "Service"), ("profile", "Profile")],
        default="service",
        required=True,
    )
    service_id = fields.Many2one("lab.service", string="Service")
    profile_id = fields.Many2one("lab.profile", string="Profile")

    quantity = fields.Integer(default=1, required=True)
    unit_price = fields.Monetary(currency_field="currency_id")
    discount_percent = fields.Float(default=0.0)
    discount_amount = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    subtotal = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    currency_id = fields.Many2one(related="request_id.currency_id", store=True, readonly=True)

    note = fields.Char()

    service_count = fields.Integer(compute="_compute_service_count", store=True)
    effective_turnaround_hours = fields.Integer(compute="_compute_tat", store=True)

    @api.depends("line_type", "profile_id.line_ids", "service_id")
    def _compute_service_count(self):
        for rec in self:
            if rec.line_type == "service":
                rec.service_count = 1 if rec.service_id else 0
            else:
                rec.service_count = len(rec.profile_id.line_ids)

    @api.depends("line_type", "service_id.turnaround_hours", "profile_id.line_ids.service_id.turnaround_hours")
    def _compute_tat(self):
        for rec in self:
            if rec.line_type == "service":
                rec.effective_turnaround_hours = rec.service_id.turnaround_hours or 0
            else:
                rec.effective_turnaround_hours = max(rec.profile_id.line_ids.mapped("service_id.turnaround_hours") or [0])

    @api.depends("quantity", "unit_price", "discount_percent")
    def _compute_amount(self):
        for rec in self:
            qty = max(rec.quantity, 0)
            gross = qty * (rec.unit_price or 0.0)
            discount = gross * ((rec.discount_percent or 0.0) / 100.0)
            rec.discount_amount = discount
            rec.subtotal = gross - discount

    @api.onchange("line_type")
    def _onchange_line_type(self):
        for rec in self:
            rec.service_id = False
            rec.profile_id = False
            rec.unit_price = 0.0

    @api.onchange("service_id")
    def _onchange_service_id(self):
        for rec in self:
            if rec.service_id and rec.line_type == "service":
                rec.unit_price = rec.service_id.list_price

    @api.onchange("profile_id")
    def _onchange_profile_id(self):
        for rec in self:
            if rec.profile_id and rec.line_type == "profile":
                prices = rec.profile_id.line_ids.mapped("service_id.list_price")
                rec.unit_price = sum(prices)

    @api.constrains("line_type", "service_id", "profile_id", "quantity")
    def _check_line(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("Quantity must be greater than 0."))
            if rec.line_type == "service" and not rec.service_id:
                raise ValidationError(_("Service line must select Service."))
            if rec.line_type == "profile" and not rec.profile_id:
                raise ValidationError(_("Profile line must select Profile."))

    def expand_to_services(self):
        self.ensure_one()
        payloads = []
        if self.line_type == "service":
            for idx in range(self.quantity):
                payloads.append(
                    {
                        "service_id": self.service_id.id,
                        "result_note": self.note
                        or (
                            _("Requested via test request line #%s") % self.id
                            if self.quantity == 1
                            else _("Requested via test request line #%s replicate %s/%s")
                            % (self.id, idx + 1, self.quantity)
                        ),
                    }
                )
            return payloads

        profile_services = self.profile_id.line_ids.mapped("service_id")
        for idx in range(self.quantity):
            for service in profile_services:
                payloads.append(
                    {
                        "service_id": service.id,
                        "result_note": self.note
                        or (
                            _("Requested via profile %(profile)s line %(line)s")
                            % {"profile": self.profile_id.name, "line": self.id}
                            if self.quantity == 1
                            else _(
                                "Requested via profile %(profile)s line %(line)s replicate %(n)s/%(q)s"
                            )
                            % {
                                "profile": self.profile_id.name,
                                "line": self.id,
                                "n": idx + 1,
                                "q": self.quantity,
                            }
                        ),
                    }
                )
        return payloads


class LabTestRequestQuoteRevision(models.Model):
    _name = "lab.test.request.quote.revision"
    _description = "Test Request Quote Revision"
    _order = "revision_no desc, id desc"

    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade")
    revision_no = fields.Integer(required=True)
    currency_id = fields.Many2one(related="request_id.currency_id", store=True, readonly=True)
    amount_untaxed = fields.Monetary(currency_field="currency_id")
    amount_discount = fields.Monetary(currency_field="currency_id")
    amount_total = fields.Monetary(currency_field="currency_id")
    quote_valid_until = fields.Date()
    quote_note = fields.Text()
    reason = fields.Char(required=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    created_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)

    @api.constrains("request_id", "revision_no")
    def _check_unique_revision(self):
        for rec in self:
            if not rec.request_id or not rec.revision_no:
                continue
            duplicate = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("request_id", "=", rec.request_id.id),
                    ("revision_no", "=", rec.revision_no),
                ]
            )
            if duplicate:
                raise ValidationError(_("Quote revision number must be unique per request."))


class LabTestRequestTimeline(models.Model):
    _name = "lab.test.request.timeline"
    _description = "Test Request Timeline"
    _order = "event_time desc, id desc"

    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade")
    event_type = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("triage", "Triage"),
            ("quoted", "Quoted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
            ("sample_created", "Sample Created"),
            ("completed", "Completed"),
        ],
        required=True,
    )
    event_time = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    note = fields.Char(required=True)
