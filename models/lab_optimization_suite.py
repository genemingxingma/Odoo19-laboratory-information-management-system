from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabWorkflowRoute(models.Model):
    _name = "lab.workflow.route"
    _description = "Laboratory Workflow Route"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    target_model = fields.Char(required=True)
    role_group_id = fields.Many2one("res.groups", string="Responsible Group")
    default_user_id = fields.Many2one("res.users", string="Responsible User")
    sop_id = fields.Many2one("lab.department.sop", string="Linked SOP")
    deadline_hours = fields.Integer(default=24)
    summary_template = fields.Char(
        string="Activity Summary",
        help="Short summary shown on generated activities. Keep it generic and reusable.",
    )
    note_template = fields.Text(
        string="Activity Note",
        help="Optional detailed note appended to generated activities.",
    )
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    _sql_constraints = [
        ("lab_workflow_route_code_company_uniq", "unique(code, company_id)", "Workflow route code must be unique per company."),
    ]

    def _resolve_user_id(self):
        self.ensure_one()
        if self.default_user_id:
            return self.default_user_id.id
        if self.role_group_id:
            user = self.env["res.users"].search([("groups_id", "in", self.role_group_id.ids), ("share", "=", False)], limit=1)
            if user:
                return user.id
        return self.env.user.id

    def create_activity_for_records(self, records, *, summary=None, note=None):
        self.ensure_one()
        records = records.filtered(lambda r: r._name == self.target_model)
        if not records:
            return 0
        deadline_hours = int(self.deadline_hours or 0)
        deadline_days = max((deadline_hours + 23) // 24, 0) if deadline_hours else 0
        deadline = fields.Date.add(fields.Date.today(), days=deadline_days)
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in records:
            body_bits = []
            if self.sop_id:
                body_bits.append(_("SOP: %s") % self.sop_id.display_name)
            if note:
                body_bits.append(note)
            elif self.note_template:
                body_bits.append(self.note_template)
            entries.append(
                {
                    "res_id": rec.id,
                    "user_id": self._resolve_user_id(),
                    "summary": summary or self.summary_template or self.name,
                    "note": "\n".join(body_bits),
                    "date_deadline": deadline,
                }
            )
        return helper.create_unique_todo_activities(model_name=self.target_model, entries=entries)


class LabActivityHelperMixin(models.AbstractModel):
    _inherit = "lab.activity.helper.mixin"

    def create_unique_todo_activities(self, *, model_name, entries):
        if not entries:
            return 0
        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not todo:
            return 0

        model_id = self.env["ir.model"]._get_id(model_name)
        res_ids = sorted({int(e["res_id"]) for e in entries if e.get("res_id")})
        user_ids = sorted({int(e["user_id"]) for e in entries if e.get("user_id")})
        summaries = sorted({e.get("summary") for e in entries if e.get("summary")})
        if not res_ids or not user_ids or not summaries:
            return 0

        existing = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", res_ids),
                ("user_id", "in", user_ids),
                ("summary", "in", summaries),
            ]
        )
        existing_keys = {(x.res_id, x.user_id.id, x.summary) for x in existing}
        vals_list = []
        for entry in entries:
            res_id = int(entry.get("res_id") or 0)
            user_id = int(entry.get("user_id") or 0)
            summary = entry.get("summary") or ""
            if not (res_id and user_id and summary):
                continue
            key = (res_id, user_id, summary)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            vals_list.append(
                {
                    "activity_type_id": todo.id,
                    "res_model_id": model_id,
                    "res_id": res_id,
                    "user_id": user_id,
                    "summary": summary,
                    "note": entry.get("note") or "",
                    "date_deadline": entry.get("date_deadline"),
                }
            )
        if not vals_list:
            return 0
        self.env["mail.activity"].create(vals_list)
        return len(vals_list)

    def route_todo_activity(self, *, route_code, records, summary=None, note=None):
        route = self.env["lab.workflow.route"].search(
            [("code", "=", route_code), ("company_id", "=", self.env.company.id), ("active", "=", True)],
            limit=1,
        )
        if not route:
            return 0
        return route.create_activity_for_records(records, summary=summary, note=note)


class LabOperationException(models.Model):
    _name = "lab.operation.exception"
    _description = "Laboratory Operation Exception"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    category = fields.Selection(
        [
            ("specimen", "Specimen"),
            ("qc", "Quality Control"),
            ("review", "Review / Release"),
            ("referral", "Referral"),
            ("pathology", "Pathology"),
            ("interface", "Interface / Import"),
            ("tat", "Turnaround Time"),
            ("billing", "Billing / Authorization"),
            ("other", "Other"),
        ],
        required=True,
        default="other",
        tracking=True,
    )
    severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        default="medium",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [("open", "Open"), ("in_progress", "In Progress"), ("resolved", "Resolved"), ("cancelled", "Cancelled")],
        default="open",
        required=True,
        tracking=True,
        index=True,
    )
    summary = fields.Char(required=True, tracking=True)
    details = fields.Text()
    assigned_user_id = fields.Many2one("res.users", string="Owner", tracking=True)
    due_date = fields.Date()
    sample_id = fields.Many2one("lab.sample", index=True)
    request_id = fields.Many2one("lab.test.request", index=True)
    referral_order_id = fields.Many2one("lab.referral.order", index=True)
    pathology_case_id = fields.Many2one("lab.pathology.case", index=True)
    capa_id = fields.Many2one("lab.nonconformance", string="Linked CAPA", readonly=True, copy=False)
    source_model = fields.Char(readonly=True)
    source_res_id = fields.Integer(readonly=True)
    source_display_name = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.operation.exception") or _("EXC")
        records = super().create(vals_list)
        helper = self.env["lab.activity.helper.mixin"]
        helper.route_todo_activity(
            route_code="exception_owner",
            records=records,
            summary=_("Resolve laboratory exception"),
            note=_("Exception %(name)s requires owner action.") % {"name": ", ".join(records.mapped("name"))},
        )
        return records

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_resolve(self):
        self.write({"state": "resolved"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_create_capa(self):
        capa_model = self.env["lab.nonconformance"]
        for rec in self:
            if rec.capa_id:
                continue
            capa = capa_model.create(
                {
                    "company_id": rec.company_id.id,
                    "title": rec.summary,
                    "description": rec.details or rec.summary,
                    "owner_id": rec.assigned_user_id.id or self.env.user.id,
                    "source_type": "manual",
                    "severity": "critical" if rec.severity == "critical" else "major" if rec.severity == "high" else "minor",
                }
            )
            rec.capa_id = capa.id
            rec.message_post(body=_("CAPA %s created from exception.") % capa.display_name)

    def action_view_source(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            raise UserError(_("No source document linked to this exception."))
        return {
            "type": "ir.actions.act_window",
            "res_model": self.source_model,
            "res_id": self.source_res_id,
            "view_mode": "form",
            "target": "current",
        }


class LabInstrumentRun(models.Model):
    _name = "lab.instrument.run"
    _description = "Laboratory Instrument Run"
    _inherit = ["mail.thread", "mail.activity.mixin", "lab.master.data.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    department = fields.Selection(selection="_selection_department", default=lambda self: self._default_department_code(), required=True, tracking=True)
    service_id = fields.Many2one("lab.service", string="Primary Service", domain="[('company_id', '=', company_id)]", tracking=True)
    instrument_id = fields.Many2one("lab.instrument", tracking=True)
    worksheet_id = fields.Many2one("lab.worksheet", tracking=True)
    plate_batch_ids = fields.One2many("lab.plate.batch", "run_id", string="Plate Batches")
    line_ids = fields.One2many("lab.instrument.run.line", "run_id", string="Sample Sheet Lines", copy=False)
    run_started_at = fields.Datetime(tracking=True)
    run_finished_at = fields.Datetime(tracking=True)
    imported_at = fields.Datetime(tracking=True)
    reviewed_at = fields.Datetime(tracking=True)
    reviewed_by_id = fields.Many2one("res.users", readonly=True, tracking=True)
    qc_summary = fields.Text()
    note = fields.Text()
    state = fields.Selection(
        [
            ("planned", "Planned"),
            ("loaded", "Loaded"),
            ("running", "Running"),
            ("imported", "Results Imported"),
            ("reviewed", "Reviewed"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        default="planned",
        required=True,
        tracking=True,
        index=True,
    )
    sample_sheet_locked = fields.Boolean(default=False, tracking=True)
    line_count = fields.Integer(compute="_compute_counts")
    imported_line_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids", "line_ids.result_state")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.imported_line_count = len(rec.line_ids.filtered(lambda x: x.result_state == "imported"))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.instrument.run") or "RUN"
        return super().create(vals_list)

    def _sync_sample_sheet_from_plates(self):
        for rec in self:
            if rec.sample_sheet_locked:
                continue
            existing_keys = {(line.analysis_id.id, line.plate_batch_line_id.id) for line in rec.line_ids}
            vals_list = []
            for plate in rec.plate_batch_ids:
                for plate_line in plate.line_ids.filtered("analysis_id"):
                    key = (plate_line.analysis_id.id, plate_line.id)
                    if key in existing_keys:
                        continue
                    vals_list.append(
                        {
                            "run_id": rec.id,
                            "analysis_id": plate_line.analysis_id.id,
                            "sample_id": plate_line.analysis_id.sample_id.id,
                            "service_id": plate_line.analysis_id.service_id.id,
                            "plate_batch_line_id": plate_line.id,
                            "well_code": plate_line.well_code,
                            "sequence": plate_line.sequence,
                            "company_id": rec.company_id.id,
                        }
                    )
            if vals_list:
                self.env["lab.instrument.run.line"].create(vals_list)

    def action_sync_sample_sheet(self):
        self._sync_sample_sheet_from_plates()
        self.write({"state": "loaded"})

    def action_lock_sample_sheet(self):
        self.write({"sample_sheet_locked": True})

    def action_start_run(self):
        self.write({"state": "running", "run_started_at": self.run_started_at or fields.Datetime.now()})

    def action_mark_imported(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("Sample sheet is empty."))
            rec.write({"state": "imported", "imported_at": fields.Datetime.now()})
            self.env["lab.activity.helper.mixin"].route_todo_activity(
                route_code="run_review",
                records=rec,
                summary=_("Review imported instrument run"),
                note=_("Run %s has imported results waiting for review.") % rec.name,
            )

    def action_mark_reviewed(self):
        self.write({"state": "reviewed", "reviewed_at": fields.Datetime.now(), "reviewed_by_id": self.env.user.id})

    def action_close(self):
        self.write({"state": "closed", "run_finished_at": self.run_finished_at or fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancelled"})


class LabInstrumentRunLine(models.Model):
    _name = "lab.instrument.run.line"
    _description = "Laboratory Instrument Run Line"
    _order = "sequence, id"

    run_id = fields.Many2one("lab.instrument.run", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    sequence = fields.Integer(default=10)
    sample_id = fields.Many2one("lab.sample", required=True, index=True)
    analysis_id = fields.Many2one("lab.sample.analysis", required=True, index=True)
    service_id = fields.Many2one("lab.service", required=True, index=True)
    plate_batch_line_id = fields.Many2one("lab.plate.batch.line", readonly=True)
    well_code = fields.Char()
    raw_result = fields.Char()
    imported_value = fields.Char()
    result_state = fields.Selection(
        [("pending", "Pending"), ("imported", "Imported"), ("applied", "Applied"), ("rejected", "Rejected")],
        default="pending",
        required=True,
        index=True,
    )
    note = fields.Char()

    def action_apply_to_analysis(self):
        for rec in self:
            if not rec.imported_value and not rec.raw_result:
                raise UserError(_("No imported value found on run line %s.") % rec.display_name)
            value = rec.imported_value or rec.raw_result
            rec.analysis_id.write({"result_value": value, "state": "done"})
            rec.result_state = "applied"


class LabPathologySynopticTemplate(models.Model):
    _name = "lab.pathology.synoptic.template"
    _description = "Pathology Synoptic Template"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    pathology_type = fields.Selection(
        [
            ("histopathology", "Histopathology"),
            ("cytopathology", "Cytopathology"),
            ("molecular_pathology", "Molecular Pathology"),
            ("hematopathology", "Hematopathology"),
            ("other", "Other"),
        ],
        default="histopathology",
        required=True,
    )
    service_ids = fields.Many2many("lab.service", string="Applicable Services")
    profile_ids = fields.Many2many("lab.profile", string="Applicable Panels")
    line_ids = fields.One2many("lab.pathology.synoptic.template.line", "template_id", string="Template Fields")

    _sql_constraints = [
        ("lab_pathology_synoptic_template_code_company_uniq", "unique(code, company_id)", "Pathology synoptic template code must be unique per company."),
    ]


class LabPathologySynopticTemplateLine(models.Model):
    _name = "lab.pathology.synoptic.template.line"
    _description = "Pathology Synoptic Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one("lab.pathology.synoptic.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True, translate=True)
    field_key = fields.Char(required=True)
    required = fields.Boolean(default=False)
    example_value = fields.Char()


class LabPartnerCatalogRule(models.Model):
    _name = "lab.partner.catalog.rule"
    _description = "Institution Catalog and Authorization Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    name = fields.Char(required=True, translate=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="partner_id.company_id", store=True, readonly=True)
    request_type = fields.Selection(
        [("individual", "Individual"), ("institution", "Institution")],
        default="institution",
        required=True,
    )
    allowed_service_ids = fields.Many2many("lab.service", string="Allowed Services")
    allowed_profile_ids = fields.Many2many("lab.profile", string="Allowed Panels")
    exclude_selected = fields.Boolean(string="Exclude Selected", default=False)
    default_report_template_id = fields.Many2one("lab.report.template", string="Default Report Template")
    preauthorization_required = fields.Boolean(default=False)
    require_contract_reference = fields.Boolean(default=False)
    credit_limit = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    refund_policy = fields.Selection(
        [("none", "No Refund"), ("manual", "Manual Review"), ("auto_before_accession", "Auto Before Accession")],
        default="manual",
    )
    recollect_policy = fields.Selection(
        [("none", "No Recollect"), ("manual", "Manual Approval"), ("included_once", "Included Once")],
        default="manual",
    )
    note = fields.Text()


class ResPartnerLabOptimization(models.Model):
    _inherit = "res.partner"

    lab_catalog_rule_ids = fields.One2many("lab.partner.catalog.rule", "partner_id", string="Lab Catalog Rules")
    lab_credit_limit = fields.Monetary(string="Lab Credit Limit", currency_field="currency_id")
    lab_credit_control_enabled = fields.Boolean(string="Enable Lab Credit Control", default=False)
    lab_open_invoice_amount = fields.Monetary(compute="_compute_lab_credit", currency_field="currency_id")

    def _compute_lab_credit(self):
        invoice_obj = self.env["lab.request.invoice"].sudo()
        for rec in self:
            invoices = invoice_obj.search(
                [
                    ("partner_id", "child_of", rec.commercial_partner_id.ids or rec.ids),
                    ("state", "in", ("issued", "partially_paid")),
                ]
            )
            rec.lab_open_invoice_amount = sum(invoices.mapped("amount_residual"))


class ProductTemplateLabOptimization(models.Model):
    _inherit = "product.template"

    lab_package_code = fields.Char(string="Package Code")
    lab_package_version = fields.Char(string="Package Version")
    lab_package_active_from = fields.Date(string="Package Active From")
    lab_package_active_to = fields.Date(string="Package Active To")
    lab_contract_only = fields.Boolean(string="Contract Only", default=False)
    lab_refund_policy = fields.Selection(
        [("none", "No Refund"), ("manual", "Manual Review"), ("auto_before_accession", "Auto Before Accession")],
        string="Refund Policy",
        default="manual",
    )
    lab_recollect_policy = fields.Selection(
        [("none", "No Recollect"), ("manual", "Manual Approval"), ("included_once", "Included Once")],
        string="Recollect Policy",
        default="manual",
    )


class LabRequestPartnerPrice(models.Model):
    _name = "lab.request.partner.price"
    _description = "Partner Specific Lab Price"
    _order = "partner_id, sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="partner_id.company_id", store=True, readonly=True)
    service_id = fields.Many2one("lab.service")
    profile_id = fields.Many2one("lab.profile")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id, required=True)
    price = fields.Monetary(required=True, currency_field="currency_id")
    contract_reference = fields.Char()
    active_from = fields.Date()
    active_to = fields.Date()

    @api.constrains("service_id", "profile_id")
    def _check_target(self):
        for rec in self:
            if bool(rec.service_id) == bool(rec.profile_id):
                raise ValidationError(_("Partner-specific price must target exactly one service or one panel."))


class LabPlateBatch(models.Model):
    _inherit = "lab.plate.batch"

    run_id = fields.Many2one("lab.instrument.run", string="Instrument Run", readonly=True, copy=False)

    def action_create_instrument_run(self):
        self.ensure_one()
        run = self.run_id
        if not run:
            run = self.env["lab.instrument.run"].create(
                {
                    "department": self.department,
                    "company_id": self.company_id.id,
                    "service_id": self.service_id.id,
                    "worksheet_id": self.worksheet_id.id,
                    "plate_batch_ids": [(4, self.id)],
                    "state": "planned",
                }
            )
            self.run_id = run.id
        else:
            run.write({"plate_batch_ids": [(4, self.id)]})
        run._sync_sample_sheet_from_plates()
        return {
            "type": "ir.actions.act_window",
            "res_model": "lab.instrument.run",
            "res_id": run.id,
            "view_mode": "form",
            "target": "current",
        }


class LabPathologyCase(models.Model):
    _inherit = "lab.pathology.case"

    synoptic_template_id = fields.Many2one("lab.pathology.synoptic.template", string="Synoptic Template")
    synoptic_item_ids = fields.One2many("lab.pathology.case.synoptic.item", "case_id", string="Synoptic Items", copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.synoptic_template_id:
                rec._assign_default_synoptic_template()
            rec._apply_synoptic_template()
        return records

    def _assign_default_synoptic_template(self):
        for rec in self:
            service_ids = rec.sample_id.analysis_ids.mapped("service_id").ids
            profile_ids = rec.sample_id.request_id.line_ids.mapped("profile_id").ids
            domain = [("company_id", "=", rec.company_id.id), ("active", "=", True)]
            template = self.env["lab.pathology.synoptic.template"].search(
                domain + ["|", ("service_ids", "in", service_ids or [0]), ("profile_ids", "in", profile_ids or [0])],
                limit=1,
            )
            if not template:
                template = self.env["lab.pathology.synoptic.template"].search(domain + [("pathology_type", "=", rec.pathology_type)], limit=1)
            if template:
                rec.synoptic_template_id = template.id

    def _apply_synoptic_template(self):
        for rec in self:
            if not rec.synoptic_template_id:
                continue
            if rec.synoptic_item_ids:
                continue
            vals_list = []
            for line in rec.synoptic_template_id.line_ids:
                vals_list.append(
                    {
                        "case_id": rec.id,
                        "sequence": line.sequence,
                        "label": line.label,
                        "field_key": line.field_key,
                        "required": line.required,
                        "value_text": line.example_value or "",
                    }
                )
            if vals_list:
                self.env["lab.pathology.case.synoptic.item"].create(vals_list)

    def action_apply_synoptic_template(self):
        self.synoptic_item_ids.unlink()
        self._apply_synoptic_template()

    def action_set_diagnosed(self):
        result = super().action_set_diagnosed()
        self.env["lab.activity.helper.mixin"].route_todo_activity(
            route_code="pathology_signoff",
            records=self,
            summary=_("Review pathology diagnosis"),
            note=_("Pathology case diagnosed and awaiting review."),
        )
        return result

    def action_set_reviewed(self):
        result = super().action_set_reviewed()
        self.env["lab.activity.helper.mixin"].route_todo_activity(
            route_code="pathology_release",
            records=self,
            summary=_("Release pathology report"),
            note=_("Pathology case reviewed and ready for report release."),
        )
        return result

    def action_release_report(self):
        for rec in self:
            missing = rec.synoptic_item_ids.filtered(lambda x: x.required and not (x.value_text or "").strip())
            if missing:
                raise UserError(
                    _("Complete required synoptic items before releasing report: %s")
                    % ", ".join(missing.mapped("label"))
                )
        return super().action_release_report()


class LabPathologyCaseSynopticItem(models.Model):
    _name = "lab.pathology.case.synoptic.item"
    _description = "Pathology Case Synoptic Item"
    _order = "sequence, id"

    case_id = fields.Many2one("lab.pathology.case", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    label = fields.Char(required=True, translate=True)
    field_key = fields.Char(required=True)
    required = fields.Boolean(default=False)
    value_text = fields.Char()


class LabReferralLab(models.Model):
    _inherit = "lab.referral.lab"

    qualification_state = fields.Selection(
        [("candidate", "Candidate"), ("approved", "Approved"), ("suspended", "Suspended"), ("expired", "Expired")],
        default="candidate",
        required=True,
    )
    last_review_date = fields.Date()
    next_review_date = fields.Date()
    kpi_tat_avg_hours = fields.Float(compute="_compute_referral_kpis", string="Average TAT (Hours)")
    open_referral_count = fields.Integer(compute="_compute_referral_kpis")
    reviewed_referral_count = fields.Integer(compute="_compute_referral_kpis")

    def _compute_referral_kpis(self):
        order_obj = self.env["lab.referral.order"].sudo()
        for rec in self:
            orders = order_obj.search([("referral_lab_id", "=", rec.id)])
            rec.open_referral_count = len(orders.filtered(lambda x: x.state not in ("completed", "cancelled")))
            rec.reviewed_referral_count = len(orders.filtered(lambda x: x.state in ("reviewed", "completed")))
            tat_values = []
            for order in orders.filtered(lambda x: x.sent_at and x.completed_at):
                tat_values.append((order.completed_at - order.sent_at).total_seconds() / 3600.0)
            rec.kpi_tat_avg_hours = sum(tat_values) / len(tat_values) if tat_values else 0.0


class LabReferralOrder(models.Model):
    _inherit = "lab.referral.order"

    expected_due_at = fields.Datetime(compute="_compute_expected_due_at", store=True)
    tat_breach = fields.Boolean(compute="_compute_expected_due_at", store=True)
    conformity_checked = fields.Boolean(string="External Report Conformity Checked", tracking=True)
    conformity_note = fields.Text(string="Conformity Note")

    @api.depends("sent_at", "referral_lab_id.expected_tat_hours", "state")
    def _compute_expected_due_at(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.expected_due_at = fields.Datetime.add(rec.sent_at, hours=rec.referral_lab_id.expected_tat_hours) if rec.sent_at else False
            rec.tat_breach = bool(
                rec.expected_due_at
                and rec.state not in ("completed", "cancelled")
                and rec.expected_due_at < now
            )

    def action_send(self):
        res = super().action_send()
        self.env["lab.activity.helper.mixin"].route_todo_activity(
            route_code="referral_followup",
            records=self,
            summary=_("Follow up referral order"),
            note=_("Referral order sent to external laboratory. Monitor SLA and returned results."),
        )
        return res

    def action_complete(self):
        for rec in self:
            if not rec.conformity_checked:
                raise UserError(_("Complete external report conformity check before completing referral order."))
        return super().action_complete()


class LabTestRequest(models.Model):
    _inherit = "lab.test.request"

    institution_catalog_rule_id = fields.Many2one("lab.partner.catalog.rule", compute="_compute_institution_rule", store=False)
    preauthorization_required = fields.Boolean(compute="_compute_institution_rule", store=False)
    preauthorization_state = fields.Selection(
        [("not_required", "Not Required"), ("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="not_required",
        tracking=True,
    )
    preauthorization_note = fields.Text()
    credit_hold = fields.Boolean(compute="_compute_institution_rule", store=False)
    catalog_scope_summary = fields.Char(compute="_compute_institution_rule")

    def _resolve_institution_rule(self):
        self.ensure_one()
        partner = self.client_partner_id.commercial_partner_id
        if not partner:
            return self.env["lab.partner.catalog.rule"]
        return self.env["lab.partner.catalog.rule"].search(
            [
                ("partner_id", "=", partner.id),
                ("request_type", "=", self.request_type),
                ("active", "=", True),
            ],
            order="sequence asc, id asc",
            limit=1,
        )

    def _compute_institution_rule(self):
        for rec in self:
            rule = rec._resolve_institution_rule() if rec.request_type == "institution" and rec.client_partner_id else self.env["lab.partner.catalog.rule"]
            partner = rec.client_partner_id.commercial_partner_id
            credit_hold = False
            if partner and partner.lab_credit_control_enabled and partner.lab_credit_limit:
                credit_hold = partner.lab_open_invoice_amount > partner.lab_credit_limit
            rec.institution_catalog_rule_id = rule
            rec.preauthorization_required = bool(rule and rule.preauthorization_required)
            rec.credit_hold = credit_hold
            rec.catalog_scope_summary = rule.display_name if rule else False

    def _enforce_partner_catalog_rule(self):
        for rec in self.filtered(lambda x: x.request_type == "institution" and x.client_partner_id):
            rule = rec._resolve_institution_rule()
            if not rule:
                continue
            if rule.default_report_template_id and not rec.preferred_template_id:
                rec.preferred_template_id = rule.default_report_template_id
            allowed_services = set(rule.allowed_service_ids.ids)
            allowed_profiles = set(rule.allowed_profile_ids.ids)
            for line in rec.line_ids:
                if line.line_type == "service" and line.service_id and allowed_services:
                    ok = line.service_id.id not in allowed_services if rule.exclude_selected else line.service_id.id in allowed_services
                    if not ok:
                        raise ValidationError(_("Service %s is not allowed by institution catalog rule.") % line.service_id.display_name)
                if line.line_type == "profile" and line.profile_id and allowed_profiles:
                    ok = line.profile_id.id not in allowed_profiles if rule.exclude_selected else line.profile_id.id in allowed_profiles
                    if not ok:
                        raise ValidationError(_("Panel %s is not allowed by institution catalog rule.") % line.profile_id.display_name)

    @api.constrains("line_ids", "client_partner_id", "request_type")
    def _check_partner_catalog_rule(self):
        self._enforce_partner_catalog_rule()

    @api.onchange("client_partner_id")
    def _onchange_client_partner_id_apply_rule(self):
        super()._onchange_client_partner_id_default_template()
        for rec in self:
            rule = rec._resolve_institution_rule() if rec.request_type == "institution" and rec.client_partner_id else self.env["lab.partner.catalog.rule"]
            if rule and rule.default_report_template_id:
                rec.preferred_template_id = rule.default_report_template_id
            if rule and rule.preauthorization_required and rec.preauthorization_state == "not_required":
                rec.preauthorization_state = "pending"

    def action_request_preauthorization(self):
        for rec in self:
            if not rec.preauthorization_required:
                rec.preauthorization_state = "not_required"
                continue
            rec.preauthorization_state = "pending"
            self.env["lab.activity.helper.mixin"].route_todo_activity(
                route_code="preauthorization_review",
                records=rec,
                summary=_("Pre-authorization review"),
                note=_("Request %s requires insurance / client pre-authorization.") % rec.name,
            )

    def action_approve_preauthorization(self):
        self.write({"preauthorization_state": "approved"})

    def action_reject_preauthorization(self):
        self.write({"preauthorization_state": "rejected"})

    def action_submit(self):
        self._enforce_partner_catalog_rule()
        for rec in self:
            if rec.preauthorization_required and rec.preauthorization_state not in ("approved",):
                raise UserError(_("Pre-authorization must be approved before submitting this request."))
            if rec.credit_hold:
                raise UserError(_("Institution is on laboratory credit hold. Resolve open balance before submitting new requests."))
        return super().action_submit()


class LabTestRequestLine(models.Model):
    _inherit = "lab.test.request.line"

    partner_specific_price_id = fields.Many2one("lab.request.partner.price", readonly=True)

    @api.depends("request_id.request_type", "request_id.company_id", "request_id.client_partner_id")
    def _compute_allowed_catalog_ids(self):
        super()._compute_allowed_catalog_ids()
        empty_services = self.env["lab.service"].browse()
        empty_profiles = self.env["lab.profile"].browse()
        for rec in self:
            request = rec.request_id
            if not request or request.request_type != "institution" or not request.client_partner_id:
                continue
            rule = request._resolve_institution_rule()
            if not rule:
                continue
            allowed_services = rule.allowed_service_ids
            allowed_profiles = rule.allowed_profile_ids
            if allowed_services:
                rec.allowed_service_ids = rec.allowed_service_ids - allowed_services if rule.exclude_selected else rec.allowed_service_ids & allowed_services
            elif not rec.allowed_service_ids:
                rec.allowed_service_ids = empty_services
            if allowed_profiles:
                rec.allowed_profile_ids = rec.allowed_profile_ids - allowed_profiles if rule.exclude_selected else rec.allowed_profile_ids & allowed_profiles
            elif not rec.allowed_profile_ids:
                rec.allowed_profile_ids = empty_profiles

    @api.onchange("service_id", "profile_id")
    def _onchange_partner_specific_price(self):
        request = self.request_id
        partner = request.client_partner_id.commercial_partner_id if request else self.env["res.partner"]
        if not partner:
            return
        today = fields.Date.today()
        for rec in self:
            domain = [("partner_id", "=", partner.id), ("active", "=", True)]
            if rec.line_type == "service" and rec.service_id:
                domain.append(("service_id", "=", rec.service_id.id))
            elif rec.line_type == "profile" and rec.profile_id:
                domain.append(("profile_id", "=", rec.profile_id.id))
            else:
                continue
            prices = self.env["lab.request.partner.price"].search(domain, order="sequence asc, id asc")
            prices = prices.filtered(lambda x: (not x.active_from or x.active_from <= today) and (not x.active_to or x.active_to >= today))
            if prices:
                rec.unit_price = prices[0].price
                rec.partner_specific_price_id = prices[0]


class LabSample(models.Model):
    _inherit = "lab.sample"

    def _create_release_exception(self, message, *, category="review", severity="high"):
        exception_obj = self.env["lab.operation.exception"]
        for rec in self:
            existing = exception_obj.search(
                [
                    ("company_id", "=", rec.company_id.id),
                    ("sample_id", "=", rec.id),
                    ("summary", "=", message),
                    ("state", "in", ("open", "in_progress")),
                ],
                limit=1,
            )
            if existing:
                continue
            exception_obj.create(
                {
                    "category": category,
                    "severity": severity,
                    "summary": message,
                    "details": _("Generated automatically while attempting report release."),
                    "sample_id": rec.id,
                    "request_id": rec.request_id.id,
                    "assigned_user_id": rec.verified_by_id.id or self.env.user.id,
                    "source_model": rec._name,
                    "source_res_id": rec.id,
                    "source_display_name": rec.display_name,
                    "company_id": rec.company_id.id,
                }
            )

    def action_release_report(self):
        for rec in self:
            blockers = []
            if hasattr(rec, "review_required_for_release") and rec.review_required_for_release and not rec.review_release_ready:
                blockers.append(rec.review_block_reason or _("Dual review is not complete."))
            if hasattr(rec, "_get_iso15189_release_blockers"):
                blockers.extend(rec._get_iso15189_release_blockers())
            if blockers:
                rec._create_release_exception("\n".join(blockers), category="review", severity="high")
        return super().action_release_report()


class LabControlCenterWizard(models.TransientModel):
    _inherit = "lab.control.center.wizard"

    exception_open_count = fields.Integer(compute="_compute_metrics")
    run_open_count = fields.Integer(compute="_compute_metrics")
    referral_followup_count = fields.Integer(compute="_compute_metrics")
    preauthorization_pending_count = fields.Integer(compute="_compute_metrics")

    def _compute_metrics(self):
        super()._compute_metrics()
        exc_obj = self.env["lab.operation.exception"]
        run_obj = self.env["lab.instrument.run"]
        referral_obj = self.env["lab.referral.order"]
        request_obj = self.env["lab.test.request"]
        exc_company = self._company_domain("lab.operation.exception")
        run_company = self._company_domain("lab.instrument.run")
        referral_company = self._company_domain("lab.referral.order")
        req_company = self._company_domain("lab.test.request")
        for rec in self:
            rec.exception_open_count = exc_obj.search_count(exc_company + [("state", "in", ("open", "in_progress"))])
            rec.run_open_count = run_obj.search_count(run_company + [("state", "in", ("planned", "loaded", "running", "imported"))])
            rec.referral_followup_count = referral_obj.search_count(referral_company + [("state", "in", ("sent", "result_received", "reviewed"))])
            rec.preauthorization_pending_count = request_obj.search_count(req_company + [("preauthorization_state", "=", "pending")])

    def action_open_exceptions(self):
        return self._action("laboratory_management.action_lab_operation_exception")

    def action_open_runs(self):
        return self._action("laboratory_management.action_lab_instrument_run")

    def action_open_referrals(self):
        return self._action("laboratory_management.action_lab_referral_order")

    def action_open_preauthorizations(self):
        action = self._action("laboratory_management.action_lab_test_request")
        action["domain"] = [("preauthorization_state", "=", "pending")]
        return action
