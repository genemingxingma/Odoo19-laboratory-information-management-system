from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabRiskRegister(models.Model):
    _name = "lab.risk.register"
    _description = "Laboratory Risk Register"
    _inherit = ["mail.thread", "mail.activity.mixin", "lab.governance.evidence.mixin"]
    _order = "priority_score desc, target_date asc, id desc"

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
            ("identified", "Identified"),
            ("assessment", "Assessment"),
            ("mitigation", "Mitigation"),
            ("monitoring", "Monitoring"),
            ("closed", "Closed"),
            ("accepted", "Accepted"),
            ("cancel", "Cancelled"),
        ],
        default="identified",
        required=True,
        tracking=True,
    )
    risk_type_id = fields.Many2one(
        "lab.risk.type",
        string="Risk Type",
        required=True,
        default=lambda self: self.env["lab.master.data.mixin"]._default_risk_type_id(),
        tracking=True,
    )
    risk_type = fields.Char(compute="_compute_legacy_type_labels", string="Risk Type (Legacy)")
    risk_owner_id = fields.Many2one("res.users", string="Risk Owner", default=lambda self: self.env.user, tracking=True)
    quality_owner_id = fields.Many2one("res.users", string="Quality Owner", tracking=True)
    identified_date = fields.Date(default=fields.Date.context_today, tracking=True)
    target_date = fields.Date(tracking=True)
    review_date = fields.Date(tracking=True)
    severity = fields.Selection(
        [("1", "1 - Negligible"), ("2", "2 - Minor"), ("3", "3 - Moderate"), ("4", "4 - Major"), ("5", "5 - Critical")],
        default="3",
        required=True,
        tracking=True,
    )
    likelihood = fields.Selection(
        [("1", "1 - Rare"), ("2", "2 - Unlikely"), ("3", "3 - Possible"), ("4", "4 - Likely"), ("5", "5 - Frequent")],
        default="3",
        required=True,
        tracking=True,
    )
    detectability = fields.Selection(
        [("1", "1 - Easily Detected"), ("2", "2 - Detected With Review"), ("3", "3 - Moderate"), ("4", "4 - Hard to Detect"), ("5", "5 - Very Hard to Detect")],
        default="3",
        required=True,
        tracking=True,
    )
    priority_score = fields.Integer(compute="_compute_priority", store=True)
    risk_level = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        compute="_compute_priority",
        store=True,
    )
    summary = fields.Text(required=True)
    source = fields.Char(string="Source / Trigger")
    potential_impact = fields.Text(required=True)
    current_controls = fields.Text()
    mitigation_plan = fields.Text()
    residual_risk_note = fields.Text()
    digital_record_only = fields.Boolean(default=True, tracking=True)
    escalation_required = fields.Boolean(default=False, tracking=True)
    closed_at = fields.Datetime(readonly=True, tracking=True)

    change_control_id = fields.Many2one("lab.change.control", string="Linked Change Control")
    nonconformance_id = fields.Many2one("lab.nonconformance", string="Linked Nonconformance")
    sample_id = fields.Many2one("lab.sample", string="Affected Sample")
    service_ids = fields.Many2many("lab.service", string="Affected Services")
    profile_ids = fields.Many2many("lab.profile", string="Affected Panels")
    instrument_ids = fields.Many2many("lab.instrument", string="Affected Instruments")
    method_validation_id = fields.Many2one("lab.method.validation", string="Linked Method Validation")
    training_id = fields.Many2one("lab.quality.training", string="Linked Training")

    is_overdue = fields.Boolean(compute="_compute_is_overdue", search="_search_is_overdue")

    _sql_constraints = [
        ("lab_risk_register_name_uniq", "unique(name)", "Risk number must be unique."),
    ]

    @api.depends("severity", "likelihood", "detectability")
    def _compute_priority(self):
        for rec in self:
            score = int(rec.severity or "1") * int(rec.likelihood or "1") * int(rec.detectability or "1")
            rec.priority_score = score
            if score >= 60:
                rec.risk_level = "critical"
            elif score >= 36:
                rec.risk_level = "high"
            elif score >= 18:
                rec.risk_level = "medium"
            else:
                rec.risk_level = "low"

    @api.depends("risk_type_id")
    def _compute_legacy_type_labels(self):
        for rec in self:
            rec.risk_type = rec.risk_type_id.display_name

    @api.depends("target_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.target_date and rec.state not in ("closed", "accepted", "cancel") and rec.target_date < today)

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        domain = [("target_date", "<", today), ("state", "not in", ("closed", "accepted", "cancel"))]
        if (operator in ("=", "==") and value) or (operator == "!=" and not value):
            return domain
        return ["!"] + domain

    @api.constrains("target_date", "identified_date")
    def _check_target_date(self):
        for rec in self:
            if rec.target_date and rec.identified_date and rec.target_date < rec.identified_date:
                raise ValidationError(_("Target date cannot be earlier than identified date."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.risk.register") or "New"
        records = super().create(vals_list)
        records._schedule_owner_activity()
        return records

    def _schedule_owner_activity(self):
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self.filtered("risk_owner_id"):
            entries.append(
                {
                    "res_id": rec.id,
                    "user_id": rec.risk_owner_id.id,
                    "summary": _("Assess laboratory risk"),
                    "note": _("Risk %(risk)s is waiting for assessment and mitigation planning.") % {"risk": rec.display_name},
                }
            )
        helper.create_unique_todo_activities(model_name=self._name, entries=entries)

    def _schedule_quality_activity(self):
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self.filtered(lambda x: x.quality_owner_id or x.risk_owner_id):
            user = rec.quality_owner_id or rec.risk_owner_id
            entries.append(
                {
                    "res_id": rec.id,
                    "user_id": user.id,
                    "summary": _("Review laboratory risk controls"),
                    "note": _("Risk %(risk)s moved to monitoring and requires quality follow-up.") % {"risk": rec.display_name},
                }
            )
        helper.create_unique_todo_activities(model_name=self._name, entries=entries)

    def action_start_assessment(self):
        self.write({"state": "assessment"})

    def action_start_mitigation(self):
        self.write({"state": "mitigation"})

    def action_start_monitoring(self):
        self.write({"state": "monitoring"})
        self._schedule_quality_activity()

    def action_accept(self):
        self.write({"state": "accepted", "closed_at": fields.Datetime.now()})

    def action_close(self):
        self.write({"state": "closed", "closed_at": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_identified(self):
        self.write({"state": "identified", "closed_at": False})

    def action_create_linked_nonconformance(self):
        for rec in self:
            if rec.nonconformance_id:
                continue
            ncr = self.env["lab.nonconformance"].create(
                {
                    "title": _("CAPA for risk %s") % rec.title,
                    "description": rec.summary or rec.potential_impact or rec.title,
                    "source_type": "manual",
                    "owner_id": rec.quality_owner_id.id or rec.risk_owner_id.id or False,
                    "severity": "critical" if rec.risk_level == "critical" else "major" if rec.risk_level == "high" else "minor",
                    "state": "open",
                }
            )
            rec.nonconformance_id = ncr.id
            rec._ensure_governance_evidence(
                evidence_type="other",
                title=_("Linked CAPA generated for %s") % rec.title,
                reference=ncr.name,
                summary=ncr.title,
                extra_vals={"risk_register_id": rec.id, "nonconformance_id": ncr.id},
            )
        return True


class LabMedicalWasteBatch(models.Model):
    _name = "lab.medical.waste.batch"
    _description = "Laboratory Medical Waste Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "collection_due_date asc, generated_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("segregated", "Segregated"),
            ("stored", "Stored"),
            ("ready", "Ready for Pickup"),
            ("disposed", "Disposed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    waste_type_id = fields.Many2one(
        "lab.waste.type",
        string="Waste Type",
        required=True,
        default=lambda self: self.env["lab.master.data.mixin"]._default_waste_type_id(),
        tracking=True,
    )
    waste_category = fields.Char(compute="_compute_legacy_labels", string="Waste Category (Legacy)")
    department_id = fields.Many2one("lab.department.type", string="Department", tracking=True)
    responsible_user_id = fields.Many2one("res.users", string="Responsible User", default=lambda self: self.env.user, tracking=True)
    vendor_partner_id = fields.Many2one("res.partner", string="Waste Vendor", tracking=True)
    generated_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    collection_due_date = fields.Date(tracking=True)
    disposed_date = fields.Datetime(tracking=True)
    quantity = fields.Float(default=1.0, tracking=True)
    quantity_uom = fields.Char(default="kg", tracking=True)
    container_count = fields.Integer(default=1, tracking=True)
    storage_location = fields.Char(tracking=True)
    manifest_reference = fields.Char(tracking=True)
    treatment_method_id = fields.Many2one(
        "lab.waste.treatment.method",
        string="Treatment Method",
        default=lambda self: self.env["lab.master.data.mixin"]._default_waste_treatment_method_id(),
        tracking=True,
    )
    treatment_method = fields.Char(compute="_compute_legacy_labels", string="Treatment Method (Legacy)")
    note = fields.Text()
    segregation_note = fields.Text()
    disposal_note = fields.Text()
    is_overdue = fields.Boolean(compute="_compute_is_overdue", search="_search_is_overdue")
    disposal_record_ids = fields.Many2many("lab.sample.disposal.record", string="Linked Disposal Records")
    risk_register_id = fields.Many2one("lab.risk.register", string="Linked Risk")

    _sql_constraints = [
        ("lab_medical_waste_batch_name_uniq", "unique(name)", "Waste batch number must be unique."),
    ]

    @api.depends("waste_type_id", "treatment_method_id")
    def _compute_legacy_labels(self):
        for rec in self:
            rec.waste_category = rec.waste_type_id.display_name
            rec.treatment_method = rec.treatment_method_id.display_name

    @api.depends("collection_due_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.collection_due_date and rec.state not in ("disposed", "cancel") and rec.collection_due_date < today)

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        domain = [("collection_due_date", "<", today), ("state", "not in", ("disposed", "cancel"))]
        if (operator in ("=", "==") and value) or (operator == "!=" and not value):
            return domain
        return ["!"] + domain

    @api.constrains("disposed_date", "generated_date")
    def _check_dates(self):
        for rec in self:
            if rec.disposed_date and rec.generated_date and rec.disposed_date < rec.generated_date:
                raise ValidationError(_("Disposed date cannot be earlier than generated date."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.medical.waste.batch") or "New"
        records = super().create(vals_list)
        records._schedule_responsible_activity(_("Segregate medical waste"), _("Waste batch %(batch)s requires segregation and containment.") )
        return records

    def _schedule_responsible_activity(self, summary, note):
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self.filtered("responsible_user_id"):
            entries.append(
                {
                    "res_id": rec.id,
                    "user_id": rec.responsible_user_id.id,
                    "summary": summary,
                    "note": note % {"batch": rec.display_name},
                }
            )
        helper.create_unique_todo_activities(model_name=self._name, entries=entries)

    def action_mark_segregated(self):
        self.write({"state": "segregated"})
        self._schedule_responsible_activity(_("Store segregated waste"), _("Waste batch %(batch)s is ready for secure temporary storage."))

    def action_mark_stored(self):
        self.write({"state": "stored"})
        self._schedule_responsible_activity(_("Prepare waste pickup"), _("Waste batch %(batch)s should be prepared for licensed pickup or treatment."))

    def action_mark_ready(self):
        self.write({"state": "ready"})

    def action_mark_disposed(self):
        self.write({"state": "disposed", "disposed_date": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft", "disposed_date": False})
