import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabTestRequest(models.Model):
    _name = "lab.test.request"
    _description = "Laboratory Test Request"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin", "lab.master.data.mixin"]
    _order = "id desc"

    name = fields.Char(string="Request No.", default="New", readonly=True, copy=False, tracking=True)
    requester_partner_id = fields.Many2one(
        "res.partner",
        string="Requester",
        default=lambda self: self.env.user.partner_id,
        required=True,
        tracking=True,
        index=True,
    )
    request_type = fields.Selection(selection="_selection_request_type", default=lambda self: self._default_request_type_code(), required=True, tracking=True, index=True)
    client_partner_id = fields.Many2one("res.partner", string="Institution / Client", tracking=True, index=True)
    patient_id = fields.Many2one("lab.patient", string="Patient", tracking=True, index=True)
    patient_name = fields.Char(string="Patient Name", tracking=True)
    patient_identifier = fields.Char(string="Patient ID / Passport", index=True)
    patient_birthdate = fields.Date(string="Date of Birth")
    patient_gender = fields.Selection(
        [("male", "Male"), ("female", "Female"), ("other", "Other"), ("unknown", "Unknown")],
        default="unknown",
    )
    patient_phone = fields.Char(string="Patient Phone")

    physician_partner_id = fields.Many2one("lab.physician", string="Physician", tracking=True)
    physician_name = fields.Char(string="Physician")
    requested_collection_date = fields.Datetime(
        string="Requested Collection Time",
        default=fields.Datetime.now,
        tracking=True,
    )
    preferred_template_id = fields.Many2one("lab.report.template", string="Preferred Report Template")
    priority = fields.Selection(selection="_selection_priority", default=lambda self: self._default_priority_code(), required=True, tracking=True)
    sample_type = fields.Selection(
        selection="_selection_sample_type",
        compute="_compute_sample_type",
        store=True,
        readonly=True,
        help="Derived from request lines. Use each line's Specimen Type as the source of truth.",
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
        index=True,
    )

    line_ids = fields.One2many("lab.test.request.line", "request_id", string="Requested Tests")
    timeline_ids = fields.One2many("lab.test.request.timeline", "request_id", string="Timeline", readonly=True)
    quote_revision_ids = fields.One2many(
        "lab.test.request.quote.revision", "request_id", string="Quote Revisions", readonly=True
    )
    sample_ids = fields.One2many("lab.sample", "request_id", string="Generated Samples", readonly=True)
    sample_count = fields.Integer(compute="_compute_sample_count")
    quote_revision_count = fields.Integer(compute="_compute_quote_revision_count")
    request_attachment_count = fields.Integer(compute="_compute_request_attachment_count")

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

    submitted_at = fields.Datetime(readonly=True, index=True)
    submitted_by_id = fields.Many2one("res.users", readonly=True)
    triaged_at = fields.Datetime(readonly=True)
    triaged_by_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True, index=True)
    approved_by_id = fields.Many2one("res.users", readonly=True)
    rejected_at = fields.Datetime(readonly=True)
    rejected_by_id = fields.Many2one("res.users", readonly=True)
    completed_at = fields.Datetime(readonly=True, index=True)

    rejection_reason = fields.Text()
    cancel_reason = fields.Text()

    estimated_turnaround_hours = fields.Integer(compute="_compute_tat", store=True)
    estimated_report_date = fields.Datetime(compute="_compute_tat", store=True)

    @api.depends("sample_ids")
    def _compute_sample_count(self):
        for rec in self:
            rec.sample_count = len(rec.sample_ids)

    def _compute_request_attachment_count(self):
        attachment_obj = self.env["ir.attachment"].sudo()
        for rec in self:
            rec.request_attachment_count = attachment_obj.search_count(
                [("res_model", "=", rec._name), ("res_id", "=", rec.id), ("type", "=", "binary")]
            )

    @api.depends("line_ids.specimen_sample_type")
    def _compute_sample_type(self):
        default_type = self._default_sample_type_code()
        for rec in self:
            line_type = next((x for x in rec.line_ids.mapped("specimen_sample_type") if x), False)
            rec.sample_type = line_type or default_type

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_test_request_company_state_created
            ON lab_test_request (company_id, state, create_date DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_test_request_requester_state
            ON lab_test_request (requester_partner_id, state)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_test_request_client_state
            ON lab_test_request (client_partner_id, state)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_test_request_patient_identifier_company
            ON lab_test_request (patient_identifier, company_id)
            """
        )

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

    @api.constrains("request_type", "line_ids.line_type", "line_ids.service_id", "line_ids.profile_id")
    def _check_line_scope_by_request_type(self):
        for rec in self:
            allowed = rec._allowed_catalog_ids_for_request_type(rec.request_type, company=rec.company_id)
            for line in rec.line_ids:
                if line.line_type == "service" and line.service_id and line.service_id.id not in allowed["service_ids"]:
                    raise ValidationError(
                        _("Service %(service)s is not allowed for request type %(request_type)s.")
                        % {"service": line.service_id.display_name, "request_type": rec.request_type}
                    )
                if line.line_type == "profile" and line.profile_id and line.profile_id.id not in allowed["profile_ids"]:
                    raise ValidationError(
                        _("Profile %(profile)s is not allowed for request type %(request_type)s.")
                        % {"profile": line.profile_id.display_name, "request_type": rec.request_type}
                    )

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.test.request") or "New"
            if not vals.get("preferred_template_id"):
                client_partner = self.env["res.partner"].browse(vals.get("client_partner_id")).commercial_partner_id
                if client_partner and client_partner.lab_default_report_template_id:
                    vals["preferred_template_id"] = client_partner.lab_default_report_template_id.id
                else:
                    default_template = self.env.ref("laboratory_management.report_template_classic", raise_if_not_found=False)
                    if default_template:
                        vals["preferred_template_id"] = default_template.id
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

    @api.model
    def _request_type_scope_record(self, request_type_code, company=None):
        company = company or self.env.company
        return (
            self.env["lab.request.type"]
            .sudo()
            .with_company(company)
            .search(
                [
                    ("code", "=", request_type_code),
                    ("active", "=", True),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )
        )

    @api.model
    def _allowed_service_domain_for_request_type(self, request_type_code, company=None):
        company = company or self.env.company
        domain = [
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("profile_only", "=", False),
        ]
        request_type = self._request_type_scope_record(request_type_code, company=company)
        if request_type and request_type.allowed_service_ids:
            if request_type.exclude_selected_services:
                domain.append(("id", "not in", request_type.allowed_service_ids.ids))
            else:
                domain.append(("id", "in", request_type.allowed_service_ids.ids or [0]))
        return domain

    @api.model
    def _allowed_profile_domain_for_request_type(self, request_type_code, company=None):
        company = company or self.env.company
        domain = [
            ("active", "=", True),
            ("company_id", "=", company.id),
        ]
        request_type = self._request_type_scope_record(request_type_code, company=company)
        if request_type and request_type.allowed_profile_ids:
            if request_type.exclude_selected_profiles:
                domain.append(("id", "not in", request_type.allowed_profile_ids.ids))
            else:
                domain.append(("id", "in", request_type.allowed_profile_ids.ids or [0]))
        return domain

    @api.model
    def _allowed_catalog_ids_for_request_type(self, request_type_code, company=None):
        company = company or self.env.company
        service_ids = set(
            self.env["lab.service"]
            .sudo()
            .with_company(company)
            .search(self._allowed_service_domain_for_request_type(request_type_code, company=company))
            .ids
        )
        profile_ids = set(
            self.env["lab.profile"]
            .sudo()
            .with_company(company)
            .search(self._allowed_profile_domain_for_request_type(request_type_code, company=company))
            .ids
        )
        return {"service_ids": service_ids, "profile_ids": profile_ids}

    @api.onchange("physician_partner_id")
    def _onchange_physician_partner_id(self):
        for rec in self:
            if rec.physician_partner_id:
                rec.physician_name = rec.physician_partner_id.name

    @api.onchange("patient_id")
    def _onchange_patient_id(self):
        for rec in self:
            if rec.patient_id:
                rec.patient_name = rec.patient_id.name
                rec.patient_identifier = rec.patient_id.identifier
                rec.patient_birthdate = rec.patient_id.birthdate
                rec.patient_gender = rec.patient_id.gender
                rec.patient_phone = rec.patient_id.phone

    @api.onchange("client_partner_id")
    def _onchange_client_partner_id_default_template(self):
        for rec in self:
            if rec.preferred_template_id:
                continue
            partner = rec.client_partner_id.commercial_partner_id if rec.client_partner_id else self.env["res.partner"]
            if partner and partner.lab_default_report_template_id:
                rec.preferred_template_id = partner.lab_default_report_template_id
            else:
                default_template = self.env.ref("laboratory_management.report_template_classic", raise_if_not_found=False)
                if default_template:
                    rec.preferred_template_id = default_template

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

    def action_view_request_attachments(self):
        self.ensure_one()
        return {
            "name": _("Request Attachments"),
            "type": "ir.actions.act_window",
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id), ("type", "=", "binary")],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
                "default_company_id": self.company_id.id,
            },
        }

    def action_open_attachment_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Add Request Attachments"),
            "res_model": "lab.test.request.attachment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "active_model": self._name,
                "active_id": self.id,
                "default_request_id": self.id,
            },
        }

    def _prepare_patient_record(self):
        self.ensure_one()
        if self.patient_id:
            return self.patient_id

        name = (self.patient_name or "").strip()
        if not name:
            name = _("Unnamed Patient")

        patient_vals = {
            "name": name,
            "phone": self.patient_phone,
            "identifier": self.patient_identifier or False,
            "birthdate": self.patient_birthdate,
            "gender": self.patient_gender,
            "company_id": self.company_id.id,
        }
        patient = self.env["lab.patient"].create(patient_vals)
        self.patient_id = patient.id
        return patient

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

            patient = rec._prepare_patient_record()
            payloads = rec._expanded_service_payloads()
            grouped_payloads = {}
            for p in payloads:
                specimen_ref = (p.get("specimen_ref") or "SP1").strip() or "SP1"
                specimen_sample_type = p.get("specimen_sample_type") or rec._default_sample_type_code()
                specimen_barcode = (p.get("specimen_barcode") or "").strip()
                key = (specimen_ref, specimen_sample_type, specimen_barcode)
                grouped_payloads.setdefault(key, [])
                grouped_payloads[key].append(p)

            created_samples = self.env["lab.sample"]
            for (specimen_ref, specimen_sample_type, specimen_barcode), specimen_payloads in grouped_payloads.items():
                note = rec.clinical_note or ""
                if specimen_ref:
                    note = ("%s\n[%s]" % (note, specimen_ref)).strip()
                sample_vals = {
                    "patient_id": patient.id,
                    "client_id": rec.client_partner_id.id or rec.requester_partner_id.commercial_partner_id.id,
                    "physician_name": rec.physician_name,
                    "company_id": rec.company_id.id,
                    "priority": rec.priority,
                    "collection_date": rec.requested_collection_date,
                    "report_template_id": rec.preferred_template_id.id,
                    "accession_barcode": specimen_barcode or False,
                    "note": note,
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
                        for p in specimen_payloads
                    ],
                }
                created_samples |= sample_model.create(sample_vals)

            rec.write({"state": "in_progress"})
            rec._log_timeline(
                "sample_created",
                _("Created %(count)s sample(s): %(samples)s")
                % {"count": len(created_samples), "samples": ", ".join(created_samples.mapped("name"))},
            )
            rec._close_sample_creation_activity()
            rec.message_post(
                body=_("Generated sample(s) <b>%(samples)s</b> from request.")
                % {"samples": ", ".join(created_samples.mapped("name"))},
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

    def _create_request_attachments(self, attachments, source="manual"):
        """Create request attachments from normalized payload list.

        attachments item schema:
        - name: str
        - content: bytes
        - mimetype: str (optional)
        """
        self.ensure_one()
        created = self.env["ir.attachment"]
        attachment_obj = self.env["ir.attachment"].sudo()
        for item in attachments or []:
            name = (item.get("name") or "").strip()
            content = item.get("content")
            if not name or not content:
                continue
            if isinstance(content, str):
                content = content.encode("utf-8")
            if not isinstance(content, (bytes, bytearray)):
                continue
            vals = {
                "name": name,
                "datas": base64.b64encode(bytes(content)),
                "mimetype": (item.get("mimetype") or "application/octet-stream").strip(),
                "res_model": self._name,
                "res_id": self.id,
                "type": "binary",
                "company_id": self.company_id.id,
            }
            created |= attachment_obj.create(vals)
        if created:
            self.message_post(
                body=_("%(count)s attachment(s) uploaded from %(source)s.")
                % {"count": len(created), "source": source},
                attachment_ids=created.ids,
                subtype_xmlid="mail.mt_note",
            )
        return created

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
    _inherit = ["lab.master.data.mixin"]
    _order = "sequence, id"

    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)

    line_type = fields.Selection(
        [("service", "Service"), ("profile", "Panel")],
        default="service",
        required=True,
    )
    specimen_ref = fields.Char(string="Specimen Ref", default="SP1", required=True)
    specimen_barcode = fields.Char(string="Container Code")
    specimen_sample_type = fields.Selection(
        selection="_selection_sample_type",
        string="Specimen Type",
        default=lambda self: self._default_sample_type_code(),
        required=True,
    )
    service_id = fields.Many2one(
        "lab.service",
        string="Service",
        domain="[('id', 'in', allowed_service_ids)]",
    )
    profile_id = fields.Many2one("lab.profile", string="Panel", domain="[('id', 'in', allowed_profile_ids)]")
    allowed_service_ids = fields.Many2many("lab.service", compute="_compute_allowed_catalog_ids", compute_sudo=True)
    allowed_profile_ids = fields.Many2many("lab.profile", compute="_compute_allowed_catalog_ids", compute_sudo=True)

    quantity = fields.Integer(default=1, required=True)
    unit_price = fields.Monetary(currency_field="currency_id")
    discount_percent = fields.Float(default=0.0)
    discount_amount = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    subtotal = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    currency_id = fields.Many2one(related="request_id.currency_id", store=True, readonly=True)

    note = fields.Char()

    service_count = fields.Integer(compute="_compute_service_count", store=True)
    effective_turnaround_hours = fields.Integer(compute="_compute_tat", store=True)

    @api.depends("request_id.request_type", "request_id.company_id")
    def _compute_allowed_catalog_ids(self):
        req_obj = self.env["lab.test.request"]
        empty_services = self.env["lab.service"].browse()
        empty_profiles = self.env["lab.profile"].browse()
        for rec in self:
            if not rec.request_id:
                rec.allowed_service_ids = empty_services
                rec.allowed_profile_ids = empty_profiles
                continue
            allowed = req_obj._allowed_catalog_ids_for_request_type(
                rec.request_id.request_type,
                company=rec.request_id.company_id,
            )
            rec.allowed_service_ids = [(6, 0, list(allowed["service_ids"]))]
            rec.allowed_profile_ids = [(6, 0, list(allowed["profile_ids"]))]

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

    @api.depends("unit_price", "discount_percent")
    def _compute_amount(self):
        for rec in self:
            qty = 1
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
                rec.specimen_sample_type = rec.service_id.sample_type or rec._default_sample_type_code()

    @api.onchange("profile_id")
    def _onchange_profile_id(self):
        for rec in self:
            if rec.profile_id and rec.line_type == "profile":
                prices = rec.profile_id.line_ids.mapped("service_id.list_price")
                rec.unit_price = sum(prices)
                rec.specimen_sample_type = getattr(rec.profile_id, "sample_type", False) or rec._default_sample_type_code()

    @api.constrains("line_type", "service_id", "profile_id", "specimen_ref", "specimen_sample_type")
    def _check_line(self):
        req_obj = self.env["lab.test.request"]
        for rec in self:
            if not (rec.specimen_ref or "").strip():
                raise ValidationError(_("Specimen Ref is required."))
            if not rec.specimen_sample_type:
                raise ValidationError(_("Specimen Type is required."))
            if rec.line_type == "service" and not rec.service_id:
                raise ValidationError(_("Service line must select Service."))
            if rec.line_type == "service" and rec.service_id and rec.service_id.profile_only:
                raise ValidationError(_("Panel-only services must be requested through a Panel line."))
            if rec.line_type == "profile" and not rec.profile_id:
                raise ValidationError(_("Panel line must select Panel."))
            if rec.request_id:
                allowed = req_obj._allowed_catalog_ids_for_request_type(
                    rec.request_id.request_type,
                    company=rec.request_id.company_id,
                )
                if rec.line_type == "service" and rec.service_id and rec.service_id.id not in allowed["service_ids"]:
                    raise ValidationError(
                        _("Service %(service)s is not allowed for request type %(request_type)s.")
                        % {"service": rec.service_id.display_name, "request_type": rec.request_id.request_type}
                    )
                if rec.line_type == "profile" and rec.profile_id and rec.profile_id.id not in allowed["profile_ids"]:
                    raise ValidationError(
                        _("Profile %(profile)s is not allowed for request type %(request_type)s.")
                        % {"profile": rec.profile_id.display_name, "request_type": rec.request_id.request_type}
                    )

    def expand_to_services(self):
        self.ensure_one()
        payloads = []
        if self.line_type == "service":
            payloads.append(
                {
                    "service_id": self.service_id.id,
                    "specimen_ref": self.specimen_ref,
                    "specimen_barcode": self.specimen_barcode,
                    "specimen_sample_type": self.specimen_sample_type,
                    "result_note": self.note or (_("Requested via test request line #%s") % self.id),
                }
            )
            return payloads

        profile_services = self.profile_id.line_ids.mapped("service_id")
        for service in profile_services:
            payloads.append(
                {
                    "service_id": service.id,
                    "specimen_ref": self.specimen_ref,
                    "specimen_barcode": self.specimen_barcode,
                    "specimen_sample_type": self.specimen_sample_type,
                    "result_note": self.note
                    or (_("Requested via panel %(profile)s line %(line)s") % {"profile": self.profile_id.name, "line": self.id}),
                }
            )
        return payloads

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["quantity"] = 1
        return super().create(vals_list)

    def write(self, vals):
        if "quantity" in vals:
            vals["quantity"] = 1
        return super().write(vals)


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
