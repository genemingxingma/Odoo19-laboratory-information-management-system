from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabChangeControl(models.Model):
    _name = "lab.change.control"
    _description = "Laboratory Change Control"
    _inherit = ["mail.thread", "mail.activity.mixin", "lab.governance.evidence.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    title = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("impact", "Impact Assessment"),
            ("approval", "Pending Approval"),
            ("approved", "Approved"),
            ("implementation", "Implementation"),
            ("validation", "Validation"),
            ("effective", "Effective"),
            ("closed", "Closed"),
            ("rejected", "Rejected"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    change_type = fields.Selection(
        [
            ("method", "Method"),
            ("report_template", "Report Template"),
            ("sop", "SOP"),
            ("catalog", "Catalog / Service / Panel"),
            ("interface", "Interface"),
            ("instrument", "Instrument"),
            ("reagent", "Reagent / Lot"),
            ("quality_rule", "Quality Rule"),
            ("authorization", "Personnel Authorization"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        tracking=True,
    )
    risk_level = fields.Selection(
        [
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        default="medium",
        required=True,
        tracking=True,
    )
    owner_user_id = fields.Many2one(
        "res.users",
        string="Change Owner",
        default=lambda self: self.env.user,
        tracking=True,
    )
    approver_user_id = fields.Many2one("res.users", string="Approver", tracking=True)
    quality_user_id = fields.Many2one("res.users", string="Quality Owner", tracking=True)
    requested_date = fields.Date(default=fields.Date.context_today, tracking=True)
    target_effective_date = fields.Date(tracking=True)
    approved_at = fields.Datetime(readonly=True, tracking=True)
    implemented_at = fields.Datetime(readonly=True, tracking=True)
    validated_at = fields.Datetime(readonly=True, tracking=True)
    effective_at = fields.Datetime(readonly=True, tracking=True)
    closed_at = fields.Datetime(readonly=True, tracking=True)
    rejected_at = fields.Datetime(readonly=True, tracking=True)
    reject_reason = fields.Text(tracking=True)

    reason = fields.Text(required=True)
    scope_summary = fields.Text(string="Scope Summary")
    impact_assessment = fields.Text()
    implementation_plan = fields.Text()
    validation_plan = fields.Text()
    training_plan = fields.Text()
    rollback_plan = fields.Text()
    effectiveness_note = fields.Text()
    approval_reference = fields.Char(
        help="External or internal approval ticket/reference number for controlled electronic approval."
    )
    approval_record_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Approval Record",
        help="Optional direct link to an approval request or equivalent record.",
    )
    controlled_document_reference = fields.Char(
        string="Controlled Document Reference",
        help="Document code, SOP number, or controlled record reference used as electronic evidence.",
    )
    controlled_document_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Controlled Document Link",
        help="Optional direct link to a controlled document or knowledge article.",
    )
    electronic_signature_reference = fields.Char(
        string="Electronic Signature Reference",
        help="Reference to electronic signature, sign request, or validated approval evidence.",
    )
    signature_record_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Signature Record",
        help="Optional direct link to a sign request or equivalent record.",
    )

    digital_record_only = fields.Boolean(
        default=True,
        help="Indicates this change is intended to be executed and evidenced electronically.",
    )
    block_release = fields.Boolean(
        string="Block Report Release Until Effective",
        default=True,
        tracking=True,
    )
    document_review_required = fields.Boolean(default=True, tracking=True)
    training_required = fields.Boolean(default=False, tracking=True)
    validation_required = fields.Boolean(default=True, tracking=True)
    document_review_complete = fields.Boolean(default=False, tracking=True)
    training_ack_complete = fields.Boolean(default=False, tracking=True)
    validation_evidence_complete = fields.Boolean(default=False, tracking=True)
    implementation_complete = fields.Boolean(default=False, tracking=True)

    service_ids = fields.Many2many("lab.service", string="Affected Services")
    profile_ids = fields.Many2many("lab.profile", string="Affected Panels")
    report_template_ids = fields.Many2many("lab.report.template", string="Affected Report Templates")
    sop_ids = fields.Many2many("lab.department.sop", string="Affected SOPs")
    interface_endpoint_ids = fields.Many2many("lab.interface.endpoint", string="Affected Interface Endpoints")
    instrument_ids = fields.Many2many("lab.instrument", string="Affected Instruments")
    reagent_lot_ids = fields.Many2many("lab.reagent.lot", string="Affected Reagent Lots")
    method_validation_ids = fields.Many2many("lab.method.validation", string="Linked Method Validations")
    training_session_ids = fields.Many2many("lab.quality.training", string="Linked Training Sessions")
    risk_register_ids = fields.Many2many("lab.risk.register", string="Linked Risks")
    nonconformance_ids = fields.Many2many("lab.nonconformance", string="Linked CAPA / Nonconformances")

    service_count = fields.Integer(compute="_compute_counts")
    profile_count = fields.Integer(compute="_compute_counts")
    training_session_count = fields.Integer(compute="_compute_counts")
    attachment_count = fields.Integer(compute="_compute_attachment_count")
    effective_ready = fields.Boolean(compute="_compute_effective_ready", store=True)
    effective_block_reason = fields.Text(compute="_compute_effective_ready", store=True)

    _sql_constraints = [
        ("lab_change_control_name_uniq", "unique(name)", "Change control number must be unique."),
    ]

    @api.depends("service_ids", "profile_ids", "training_session_ids")
    def _compute_counts(self):
        for rec in self:
            rec.service_count = len(rec.service_ids)
            rec.profile_count = len(rec.profile_ids)
            rec.training_session_count = len(rec.training_session_ids)

    @api.depends(
        "state",
        "document_review_required",
        "document_review_complete",
        "training_required",
        "training_ack_complete",
        "validation_required",
        "validation_evidence_complete",
        "implementation_complete",
        "method_validation_ids.state",
        "training_session_ids.state",
        "approval_reference",
        "approval_record_ref",
        "controlled_document_reference",
        "controlled_document_ref",
        "electronic_signature_reference",
        "signature_record_ref",
    )
    def _compute_effective_ready(self):
        for rec in self:
            blockers = rec._get_effective_blockers()
            rec.effective_ready = not blockers
            rec.effective_block_reason = "\n".join("- %s" % item for item in blockers) if blockers else False

    def _compute_attachment_count(self):
        attachment_obj = self.env["ir.attachment"].sudo()
        for rec in self:
            rec.attachment_count = attachment_obj.search_count(
                [("res_model", "=", rec._name), ("res_id", "=", rec.id)]
            )

    @api.model
    def _selection_governance_reference_models(self):
        return self.env["lab.governance.evidence"]._selection_governance_reference_models()

    @api.onchange("approval_record_ref")
    def _onchange_approval_record_ref(self):
        for rec in self:
            if rec.approval_record_ref and not rec.approval_reference:
                rec.approval_reference = rec.approval_record_ref.display_name

    @api.onchange("controlled_document_ref")
    def _onchange_controlled_document_ref(self):
        for rec in self:
            if rec.controlled_document_ref and not rec.controlled_document_reference:
                rec.controlled_document_reference = rec.controlled_document_ref.display_name

    @api.onchange("signature_record_ref")
    def _onchange_signature_record_ref(self):
        for rec in self:
            if rec.signature_record_ref and not rec.electronic_signature_reference:
                rec.electronic_signature_reference = rec.signature_record_ref.display_name

    @api.constrains("target_effective_date", "requested_date")
    def _check_dates(self):
        for rec in self:
            if rec.target_effective_date and rec.requested_date and rec.target_effective_date < rec.requested_date:
                raise ValidationError(_("Target effective date cannot be earlier than requested date."))

    @api.constrains("state", "approver_user_id")
    def _check_approval_owner(self):
        for rec in self:
            if rec.state in ("approval", "approved", "implementation", "validation", "effective", "closed") and not rec.approver_user_id:
                raise ValidationError(_("Approver is required before entering approval workflow."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.change.control") or "New"
        records = super().create(vals_list)
        records._schedule_owner_activity()
        return records

    def _get_effective_blockers(self):
        self.ensure_one()
        blockers = []
        if self.state not in ("approved", "implementation", "validation"):
            blockers.append(_("Change must be approved before it can become effective."))
        if not self.implementation_complete:
            blockers.append(_("Implementation confirmation is still missing."))
        if self.digital_record_only:
            if not ((self.approval_reference or "").strip() or self.approval_record_ref):
                blockers.append(_("Electronic approval reference is missing."))
            if self.document_review_required and not (
                (self.controlled_document_reference or "").strip() or self.controlled_document_ref
            ):
                blockers.append(_("Controlled document reference is missing."))
            if not ((self.electronic_signature_reference or "").strip() or self.signature_record_ref):
                blockers.append(_("Electronic signature reference is missing."))
        if self.document_review_required and not self.document_review_complete:
            blockers.append(_("Controlled document review is not completed."))
        if self.training_required and not self.training_ack_complete:
            blockers.append(_("Training acknowledgement is not completed."))
        if self.training_required:
            done_trainings = self.training_session_ids.filtered(lambda x: x.state == "done")
            if not done_trainings:
                blockers.append(_("At least one completed linked training session is required."))
        if self.validation_required:
            approved_validations = self.method_validation_ids.filtered(lambda x: x.state == "approved")
            if self.method_validation_ids and not approved_validations:
                blockers.append(_("Linked method validations are not approved yet."))
            elif not self.method_validation_ids and not self.validation_evidence_complete:
                blockers.append(_("Validation evidence is not completed."))
        return blockers

    def _activity_helper(self):
        return self.env["lab.activity.helper.mixin"]

    def _schedule_activity(self, *, user, summary, note):
        if not user:
            return 0
        return self._activity_helper().create_unique_todo_activities(
            model_name=self._name,
            entries=[
                {
                    "res_id": rec.id,
                    "user_id": user.id,
                    "summary": summary,
                    "note": note,
                }
                for rec in self
            ],
        )

    def _schedule_owner_activity(self):
        for rec in self:
            rec._schedule_activity(
                user=rec.owner_user_id,
                summary=_("Prepare change assessment"),
                note=_("Change %(name)s is waiting for impact assessment and implementation planning.")
                % {"name": rec.display_name},
            )

    def _schedule_approver_activity(self):
        for rec in self:
            rec._schedule_activity(
                user=rec.approver_user_id,
                summary=_("Approve laboratory change"),
                note=_("Change %(name)s is waiting for approval review.") % {"name": rec.display_name},
            )

    def _schedule_quality_activity(self):
        for rec in self:
            rec._schedule_activity(
                user=rec.quality_user_id or rec.approver_user_id,
                summary=_("Verify change effectiveness"),
                note=_("Change %(name)s is waiting for validation and effectiveness confirmation.")
                % {"name": rec.display_name},
            )

    def _create_governance_evidence_bundle(self, stage):
        for rec in self:
            if stage in ("approval_requested", "approved"):
                rec._ensure_governance_evidence(
                    evidence_type="approval",
                    title=_("Approval evidence for %s") % rec.title,
                    reference=rec.approval_reference or (rec.approval_record_ref.display_name if rec.approval_record_ref else False),
                    summary=rec.impact_assessment or rec.reason or rec.title,
                    approval_record_ref=rec.approval_record_ref or False,
                    extra_vals={"change_control_id": rec.id},
                )
            if stage in ("effective", "document"):
                if rec.document_review_required:
                    rec._ensure_governance_evidence(
                        evidence_type="document",
                        title=_("Controlled document evidence for %s") % rec.title,
                        reference=rec.controlled_document_reference or (rec.controlled_document_ref.display_name if rec.controlled_document_ref else False),
                        summary=rec.scope_summary or rec.reason or rec.title,
                        controlled_document_ref=rec.controlled_document_ref or False,
                        extra_vals={"change_control_id": rec.id},
                    )
            if stage in ("effective", "signature"):
                rec._ensure_governance_evidence(
                    evidence_type="signature",
                    title=_("Signature evidence for %s") % rec.title,
                    reference=rec.electronic_signature_reference or (rec.signature_record_ref.display_name if rec.signature_record_ref else False),
                    summary=rec.effectiveness_note or rec.validation_plan or rec.title,
                    signature_record_ref=rec.signature_record_ref or False,
                    extra_vals={"change_control_id": rec.id},
                )
            if stage in ("implemented", "effective"):
                if rec.validation_required:
                    for validation in rec.method_validation_ids:
                        rec._ensure_governance_evidence(
                            evidence_type="validation",
                            title=_("Validation evidence for %s") % validation.display_name,
                            reference=validation.name,
                            summary=validation.summary_result or validation.plan_note or validation.display_name,
                            extra_vals={
                                "change_control_id": rec.id,
                                "method_validation_id": validation.id,
                            },
                        )
            if stage in ("effective", "training") and rec.training_required:
                for training in rec.training_session_ids.filtered(lambda x: x.state == "done"):
                    rec._ensure_governance_evidence(
                        evidence_type="training",
                        title=_("Training evidence for %s") % training.display_name,
                        reference=training.name,
                        summary=training.topic or training.note or training.display_name,
                        extra_vals={
                            "change_control_id": rec.id,
                            "training_id": training.id,
                        },
                    )

    def _post_effective_messages(self):
        for rec in self:
            body = _(
                "Change control <b>%(change)s</b> became effective on %(date)s."
            ) % {
                "change": rec.display_name,
                "date": rec.effective_at or fields.Datetime.now(),
            }
            for target in (
                rec.service_ids
                | rec.profile_ids
                | rec.report_template_ids
                | rec.sop_ids
                | rec.interface_endpoint_ids
                | rec.instrument_ids
                | rec.reagent_lot_ids
                | rec.method_validation_ids
            ):
                if hasattr(target, "message_post"):
                    target.message_post(body=body)

    def action_submit_impact(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                continue
            rec.state = "impact"

    def action_request_approval(self):
        for rec in self:
            if rec.state not in ("draft", "impact", "rejected"):
                continue
            if not (rec.impact_assessment or "").strip():
                raise UserError(_("Impact assessment is required before approval request."))
            if not (rec.implementation_plan or "").strip():
                raise UserError(_("Implementation plan is required before approval request."))
            if not (rec.rollback_plan or "").strip():
                raise UserError(_("Rollback plan is required before approval request."))
            if not rec.approver_user_id:
                raise UserError(_("Approver is required before approval request."))
            if rec.digital_record_only and not ((rec.approval_reference or "").strip() or rec.approval_record_ref):
                raise UserError(_("Approval reference is required for electronic-only change control."))
            rec.state = "approval"
            rec._create_governance_evidence_bundle("approval_requested")
            rec._schedule_approver_activity()

    def action_approve(self):
        for rec in self:
            if rec.state != "approval":
                continue
            rec.write(
                {
                    "state": "approved",
                    "approved_at": fields.Datetime.now(),
                    "reject_reason": False,
                    "rejected_at": False,
                }
            )
            rec._create_governance_evidence_bundle("approved")
            rec._schedule_owner_activity()

    def action_reject(self):
        for rec in self:
            if rec.state not in ("approval", "approved", "implementation", "validation"):
                continue
            if not (rec.reject_reason or "").strip():
                raise UserError(_("Reject reason is required."))
            rec.write({"state": "rejected", "rejected_at": fields.Datetime.now()})

    def action_start_implementation(self):
        for rec in self:
            if rec.state != "approved":
                continue
            rec.state = "implementation"

    def action_mark_implemented(self):
        for rec in self:
            if rec.state not in ("approved", "implementation"):
                continue
            rec.write(
                {
                    "state": "validation" if rec.validation_required else "implementation",
                    "implementation_complete": True,
                    "implemented_at": fields.Datetime.now(),
                }
            )
            rec._create_governance_evidence_bundle("implemented")
            rec._schedule_quality_activity()

    def action_mark_validated(self):
        for rec in self:
            if rec.state not in ("implementation", "validation"):
                continue
            rec.write({"state": "validation", "validated_at": fields.Datetime.now()})

    def action_mark_effective(self):
        for rec in self:
            blockers = rec._get_effective_blockers()
            if blockers:
                raise UserError("\n".join(blockers))
            rec.write(
                {
                    "state": "effective",
                    "effective_at": fields.Datetime.now(),
                }
            )
            rec._create_governance_evidence_bundle("effective")
            rec._post_effective_messages()

    def action_close(self):
        for rec in self:
            if rec.state != "effective":
                continue
            rec.write({"state": "closed", "closed_at": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

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

    def action_create_linked_risk(self):
        for rec in self:
            if rec.risk_register_ids:
                continue
            risk = self.env["lab.risk.register"].create(
                {
                    "title": _("Risk for %s") % rec.title,
                    "summary": rec.reason or rec.impact_assessment or rec.title,
                    "potential_impact": rec.impact_assessment or rec.reason or rec.title,
                    "current_controls": rec.scope_summary or False,
                    "mitigation_plan": rec.implementation_plan or False,
                    "risk_owner_id": rec.owner_user_id.id or self.env.user.id,
                    "quality_owner_id": rec.quality_user_id.id or rec.approver_user_id.id or False,
                    "change_control_id": rec.id,
                    "service_ids": [(6, 0, rec.service_ids.ids)],
                    "profile_ids": [(6, 0, rec.profile_ids.ids)],
                    "instrument_ids": [(6, 0, rec.instrument_ids.ids)],
                }
            )
            rec.risk_register_ids = [(4, risk.id)]
            rec._ensure_governance_evidence(
                evidence_type="other",
                title=_("Linked risk generated for %s") % rec.title,
                reference=risk.name,
                summary=risk.title,
                extra_vals={"change_control_id": rec.id, "risk_register_id": risk.id},
            )
        return True

    def action_create_linked_nonconformance(self):
        for rec in self:
            if rec.nonconformance_ids:
                continue
            ncr = self.env["lab.nonconformance"].create(
                {
                    "title": _("CAPA for %s") % rec.title,
                    "description": rec.impact_assessment or rec.reason or rec.title,
                    "source_type": "manual",
                    "owner_id": rec.quality_user_id.id or rec.owner_user_id.id or False,
                    "severity": "critical" if rec.risk_level == "critical" else "major" if rec.risk_level == "high" else "minor",
                    "state": "open",
                    "change_control_id": rec.id,
                }
            )
            rec.nonconformance_ids = [(4, ncr.id)]
            rec._ensure_governance_evidence(
                evidence_type="other",
                title=_("Linked CAPA generated for %s") % rec.title,
                reference=ncr.name,
                summary=ncr.title,
                extra_vals={"change_control_id": rec.id, "nonconformance_id": ncr.id},
            )
        return True

    @api.model
    def _find_active_release_blocking_changes(self, *, company, services=None, report_template=None):
        domain = [
            ("company_id", "=", company.id),
            ("block_release", "=", True),
            ("state", "in", ("approval", "approved", "implementation", "validation")),
        ]
        branches = []
        if services:
            branches.append([("service_ids", "in", services.ids)])
        if report_template:
            branches.append([("report_template_ids", "in", report_template.ids)])
        if not branches:
            return self.browse()
        combined = []
        for branch in branches:
            if combined:
                combined = ["|"] + combined + branch
            else:
                combined = branch
        return self.search(domain + combined)
