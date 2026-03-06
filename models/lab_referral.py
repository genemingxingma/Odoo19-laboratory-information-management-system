from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabReferralLab(models.Model):
    _name = "lab.referral.lab"
    _description = "Referral Laboratory"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    partner_id = fields.Many2one("res.partner", string="Partner")
    accreditation_body = fields.Char(string="Accreditation Body")
    accreditation_number = fields.Char(string="Accreditation Number")
    accreditation_scope = fields.Text(string="Accreditation Scope")
    accreditation_valid_until = fields.Date(string="Accreditation Valid Until")
    contact_person = fields.Char()
    contact_phone = fields.Char()
    contact_email = fields.Char()
    expected_tat_hours = fields.Integer(string="Expected TAT (Hours)", default=72)
    report_format_note = fields.Text(string="Report Format Note")
    sla_note = fields.Text(string="SLA Note")
    note = fields.Text()

    service_ids = fields.Many2many(
        "lab.service",
        "lab_referral_lab_service_rel",
        "referral_lab_id",
        "service_id",
        string="Supported Services",
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
    )
    panel_ids = fields.Many2many(
        "lab.profile",
        "lab_referral_lab_profile_rel",
        "referral_lab_id",
        "profile_id",
        string="Supported Panels",
        domain="[('active', '=', True), ('company_id', '=', company_id)]",
    )

    _sql_constraints = [
        ("lab_referral_lab_code_company_uniq", "unique(code, company_id)", "Referral lab code must be unique per company."),
    ]


class LabServiceReferralExtension(models.Model):
    _inherit = "lab.service"

    allow_referral = fields.Boolean(string="Allow Referral Testing", default=False)
    default_referral_lab_id = fields.Many2one(
        "lab.referral.lab",
        string="Default Referral Lab",
        domain="[('active','=',True), ('company_id', '=', company_id)]",
    )

    @api.constrains("allow_referral", "default_referral_lab_id")
    def _check_referral_default(self):
        for rec in self:
            if rec.default_referral_lab_id and not rec.allow_referral:
                raise ValidationError(_("Enable 'Allow Referral Testing' before setting a default referral lab."))


class LabSampleReferralExtension(models.Model):
    _inherit = "lab.sample"

    referral_order_ids = fields.One2many("lab.referral.order", "sample_id", string="Referral Orders", readonly=True)
    referral_order_count = fields.Integer(compute="_compute_referral_order_count")

    def _compute_referral_order_count(self):
        for rec in self:
            rec.referral_order_count = len(rec.referral_order_ids)

    def action_view_referral_orders(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("laboratory_management.action_lab_referral_order")
        action["domain"] = [("sample_id", "=", self.id)]
        action["context"] = {
            "default_sample_id": self.id,
            "default_request_id": self.request_id.id,
            "default_patient_id": self.patient_id.id,
            "default_client_id": self.client_id.id,
            "default_company_id": self.company_id.id,
        }
        return action

    def action_create_referral_order(self):
        self.ensure_one()
        if self.state == "cancel":
            raise UserError(_("Cancelled samples cannot create referral orders."))
        action = self.env["ir.actions.actions"]._for_xml_id("laboratory_management.action_lab_referral_order")
        action["views"] = [(False, "form")]
        action["target"] = "current"
        action["context"] = {
            "default_sample_id": self.id,
            "default_request_id": self.request_id.id,
            "default_patient_id": self.patient_id.id,
            "default_client_id": self.client_id.id,
            "default_company_id": self.company_id.id,
        }
        return action

    def _has_open_referral_orders(self):
        self.ensure_one()
        return bool(self.referral_order_ids.filtered(lambda x: x.state not in ("completed", "cancelled")))

    def action_release_report(self):
        for rec in self:
            if rec._has_open_referral_orders():
                raise UserError(_("This sample has open referral orders. Complete or cancel them before releasing report."))
        return super().action_release_report()


class LabReferralOrder(models.Model):
    _name = "lab.referral.order"
    _description = "Referral Testing Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Referral No.", default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    sample_id = fields.Many2one(
        "lab.sample",
        required=True,
        tracking=True,
        domain="[('company_id', '=', company_id)]",
    )
    request_id = fields.Many2one("lab.test.request", tracking=True, readonly=True)
    patient_id = fields.Many2one("lab.patient", tracking=True, readonly=True)
    client_id = fields.Many2one("res.partner", string="Institution / Client", tracking=True, readonly=True)
    referral_lab_id = fields.Many2one(
        "lab.referral.lab",
        string="Referral Lab",
        required=True,
        tracking=True,
        domain="[('active','=',True), ('company_id', '=', company_id)]",
    )
    reason = fields.Selection(
        [
            ("capacity", "Capacity Overload"),
            ("method_unavailable", "Method Unavailable"),
            ("instrument_down", "Instrument Down"),
            ("confirmatory", "Confirmatory Test"),
            ("other", "Other"),
        ],
        default="capacity",
        required=True,
        tracking=True,
    )
    reason_note = fields.Text(string="Reason Detail")

    line_ids = fields.One2many("lab.referral.order.line", "order_id", string="Referral Analyses", copy=True)
    line_count = fields.Integer(compute="_compute_line_count")
    completed_line_count = fields.Integer(compute="_compute_line_count")

    sent_at = fields.Datetime(readonly=True, tracking=True)
    sent_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    result_received_at = fields.Datetime(readonly=True, tracking=True)
    result_received_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    reviewed_at = fields.Datetime(readonly=True, tracking=True)
    reviewed_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    completed_at = fields.Datetime(readonly=True, tracking=True)
    completed_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    cancel_reason = fields.Text()
    note = fields.Text()

    attachment_count = fields.Integer(compute="_compute_attachment_count")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("sent", "Sent"),
            ("result_received", "Result Received"),
            ("reviewed", "Reviewed"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        index=True,
    )

    def _compute_attachment_count(self):
        att_obj = self.env["ir.attachment"].sudo()
        for rec in self:
            rec.attachment_count = att_obj.search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id)])

    @api.depends("line_ids.state")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.completed_line_count = len(rec.line_ids.filtered(lambda x: x.state == "applied"))

    @api.onchange("sample_id")
    def _onchange_sample_id(self):
        for rec in self:
            rec.request_id = rec.sample_id.request_id
            rec.patient_id = rec.sample_id.patient_id
            rec.client_id = rec.sample_id.client_id
            if not rec.line_ids and rec.sample_id:
                allowed = rec.sample_id.analysis_ids.filtered(lambda x: x.service_id.allow_referral)
                rec.line_ids = [(0, 0, {"analysis_id": x.id}) for x in allowed]

    @api.constrains("line_ids")
    def _check_lines(self):
        for rec in self:
            if rec.state != "cancelled" and not rec.line_ids:
                raise ValidationError(_("Referral order requires at least one analysis line."))

    @api.constrains("sample_id", "line_ids")
    def _check_line_sample_consistency(self):
        for rec in self:
            for line in rec.line_ids:
                if line.analysis_id.sample_id != rec.sample_id:
                    raise ValidationError(_("All analysis lines must belong to the selected sample."))

    @api.constrains("referral_lab_id", "line_ids")
    def _check_referral_lab_coverage(self):
        for rec in self:
            if not rec.referral_lab_id or not rec.line_ids:
                continue
            supported_services = rec.referral_lab_id.service_ids
            if not supported_services:
                continue
            unsupported = rec.line_ids.filtered(lambda x: x.service_id not in supported_services)
            if unsupported:
                raise ValidationError(
                    _("Referral lab %(lab)s does not cover services: %(services)s")
                    % {
                        "lab": rec.referral_lab_id.display_name,
                        "services": ", ".join(unsupported.mapped("service_id.display_name")),
                    }
                )

    @api.model_create_multi
    def create(self, vals_list):
        seq_obj = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_obj.next_by_code("lab.referral.order") or "New"
        records = super().create(vals_list)
        return records

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                continue
            rec.state = "submitted"

    def action_approve(self):
        for rec in self:
            if rec.state != "submitted":
                continue
            rec.state = "approved"

    def action_send(self):
        for rec in self:
            if rec.state not in ("approved", "submitted"):
                continue
            rec.write(
                {
                    "state": "sent",
                    "sent_at": fields.Datetime.now(),
                    "sent_by_id": self.env.user.id,
                }
            )
            rec.line_ids.filtered(lambda x: x.state == "draft").write({"state": "sent"})

    def action_mark_result_received(self):
        for rec in self:
            if rec.state not in ("sent", "approved"):
                continue
            rec.write(
                {
                    "state": "result_received",
                    "result_received_at": fields.Datetime.now(),
                    "result_received_by_id": self.env.user.id,
                }
            )
            rec.line_ids.filtered(lambda x: x.state in ("draft", "sent")).write({"state": "received"})

    def action_mark_reviewed(self):
        for rec in self:
            if rec.state != "result_received":
                continue
            rec.write(
                {
                    "state": "reviewed",
                    "reviewed_at": fields.Datetime.now(),
                    "reviewed_by_id": self.env.user.id,
                }
            )

    def action_apply_results_to_sample(self):
        for rec in self:
            if rec.state not in ("result_received", "reviewed"):
                raise UserError(_("Apply results only after external results are received."))
            for line in rec.line_ids:
                line.action_apply_result()

    def action_complete(self):
        for rec in self:
            if rec.state not in ("reviewed", "result_received"):
                continue
            rec.action_apply_results_to_sample()
            rec.write(
                {
                    "state": "completed",
                    "completed_at": fields.Datetime.now(),
                    "completed_by_id": self.env.user.id,
                }
            )
            rec.sample_id.message_post(
                body=_("Referral order %(name)s completed by %(user)s.") % {"name": rec.name, "user": self.env.user.display_name}
            )

    def action_cancel(self):
        for rec in self:
            rec.state = "cancelled"

    def action_view_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Attachments"),
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }


class LabReferralOrderLine(models.Model):
    _name = "lab.referral.order.line"
    _description = "Referral Order Line"
    _order = "id"

    order_id = fields.Many2one("lab.referral.order", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="order_id.company_id", store=True, readonly=True, index=True)
    analysis_id = fields.Many2one(
        "lab.sample.analysis",
        required=True,
    )
    sample_id = fields.Many2one(related="order_id.sample_id", store=True, readonly=True)
    service_id = fields.Many2one(related="analysis_id.service_id", store=True, readonly=True)

    external_result_value = fields.Char(string="External Result")
    external_result_note = fields.Char(string="External Note")
    external_reference = fields.Char(string="External Reference")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Sent"),
            ("received", "Received"),
            ("applied", "Applied"),
        ],
        default="draft",
        required=True,
    )
    applied_at = fields.Datetime(readonly=True)
    applied_by_id = fields.Many2one("res.users", readonly=True)

    @api.constrains("analysis_id", "order_id")
    def _check_unique_analysis_per_order(self):
        for rec in self:
            if not rec.analysis_id or not rec.order_id:
                continue
            dup = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("order_id", "=", rec.order_id.id),
                    ("analysis_id", "=", rec.analysis_id.id),
                ]
            )
            if dup:
                raise ValidationError(_("The same analysis cannot appear twice in one referral order."))

    @api.constrains("analysis_id")
    def _check_service_referral_allowed(self):
        for rec in self:
            if rec.analysis_id and not rec.analysis_id.service_id.allow_referral:
                raise ValidationError(
                    _("Service %(service)s is not configured for referral testing.")
                    % {"service": rec.analysis_id.service_id.display_name}
                )

    def action_apply_result(self):
        for rec in self:
            if not rec.external_result_value:
                raise UserError(_("Please input external result value before applying to analysis."))
            analysis = rec.analysis_id
            analysis.write(
                {
                    "result_value": rec.external_result_value,
                    "result_note": rec.external_result_note,
                    "state": "done" if analysis.state != "verified" else analysis.state,
                    "auto_verified": False,
                }
            )
            rec.write(
                {
                    "state": "applied",
                    "applied_at": fields.Datetime.now(),
                    "applied_by_id": self.env.user.id,
                }
            )
            analysis.sample_id.message_post(
                body=_("External referral result applied for service %(service)s from referral order %(order)s.")
                % {"service": analysis.service_id.display_name, "order": rec.order_id.name}
            )
        self.mapped("analysis_id")._sync_sample_states()
