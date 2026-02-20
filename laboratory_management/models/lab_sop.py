from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabRetestPolicy(models.Model):
    _name = "lab.retest.policy"
    _description = "Laboratory Retest Policy"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    scope = fields.Selection(
        [("department", "Department"), ("service", "Service")],
        required=True,
        default="department",
    )
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
    )
    service_ids = fields.Many2many("lab.service", string="Services")
    max_retest_count = fields.Integer(default=1, required=True)
    require_reason = fields.Boolean(default=True)
    cooldown_minutes = fields.Integer(default=0)
    escalate_after_failures = fields.Integer(
        default=2,
        help="Create NCR/escalation once rejected+retest history reaches this number.",
    )
    escalation_group_id = fields.Many2one("res.groups", string="Escalation Group")
    active = fields.Boolean(default=True)
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "Retest policy code must be unique.")

    @api.constrains("max_retest_count", "cooldown_minutes", "escalate_after_failures")
    def _check_non_negative(self):
        for rec in self:
            if rec.max_retest_count < 0 or rec.cooldown_minutes < 0 or rec.escalate_after_failures < 0:
                raise ValidationError(_("Retest policy numeric limits must be non-negative."))
            if rec.scope == "department" and not rec.department:
                raise ValidationError(_("Department scope policy must define department."))

    def matches_analysis(self, analysis):
        self.ensure_one()
        if self.scope == "service":
            return analysis.service_id in self.service_ids
        return analysis.department == self.department


class LabDepartmentSop(models.Model):
    _name = "lab.department.sop"
    _description = "Laboratory Department SOP"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "department, name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
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
        default="other",
    )
    priority = fields.Selection(
        [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT"), ("all", "All")],
        default="all",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Active"), ("retired", "Retired")],
        default="draft",
        tracking=True,
    )
    step_ids = fields.One2many("lab.department.sop.step", "sop_id", string="SOP Steps")
    exception_route_ids = fields.One2many("lab.sop.exception.route", "sop_id", string="Exception Routes")
    retest_policy_id = fields.Many2one("lab.retest.policy", string="Retest Policy")
    service_ids = fields.Many2many("lab.service", string="Applicable Services")
    active = fields.Boolean(default=True)
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "SOP code must be unique.")

    @api.constrains("step_ids")
    def _check_step(self):
        for rec in self:
            if rec.state == "active" and not rec.step_ids:
                raise ValidationError(_("Active SOP must define at least one SOP step."))

    def action_activate(self):
        for rec in self:
            if not rec.step_ids:
                raise UserError(_("Please add SOP steps before activation."))
            rec.state = "active"
        return True

    def action_retire(self):
        self.write({"state": "retired"})
        return True

    def action_reset_draft(self):
        self.write({"state": "draft"})
        return True

    @api.model
    def find_best_sop(self, sample, analysis=False):
        domain = [("state", "=", "active"), ("department", "=", False)]
        if analysis and analysis.department:
            domain = [("state", "=", "active"), ("department", "=", analysis.department)]
        elif sample.analysis_ids:
            first_dept = sample.analysis_ids[:1].department
            if first_dept:
                domain = [("state", "=", "active"), ("department", "=", first_dept)]

        candidates = self.search(domain)
        if not candidates and analysis and analysis.department:
            candidates = self.search([("state", "=", "active"), ("department", "=", analysis.department)])
        if not candidates and sample.analysis_ids:
            dept = sample.analysis_ids[:1].department
            candidates = self.search([("state", "=", "active"), ("department", "=", dept)])
        if not candidates:
            return False

        preferred = candidates.filtered(
            lambda s: (
                (s.sample_type in (False, "other", sample.analysis_ids[:1].sample_type if sample.analysis_ids else "other"))
                and (s.priority in ("all", sample.priority))
            )
        )
        return (preferred or candidates)[:1]


class LabDepartmentSopStep(models.Model):
    _name = "lab.department.sop.step"
    _description = "SOP Step"
    _order = "sop_id, sequence, id"

    sequence = fields.Integer(default=10)
    sop_id = fields.Many2one("lab.department.sop", required=True, ondelete="cascade", index=True)
    step_code = fields.Char(required=True)
    name = fields.Char(required=True)
    workstation_role = fields.Selection(
        [
            ("reception", "Reception"),
            ("analyst", "Analyst"),
            ("reviewer", "Reviewer"),
            ("manager", "Manager"),
        ],
        default="analyst",
        required=True,
    )
    required = fields.Boolean(default=True)
    max_hours_from_prev = fields.Integer(default=0)
    on_fail_action = fields.Selection(
        [
            ("hold", "Hold"),
            ("manual_review", "Manual Review"),
            ("retest", "Retest"),
            ("recollect", "Re-collect"),
            ("ncr", "Create NCR"),
        ],
        default="manual_review",
    )
    control_note = fields.Text()

    _step_code_uniq = models.Constraint("unique(sop_id, step_code)", "Step code must be unique within SOP.")


class LabSopExceptionRoute(models.Model):
    _name = "lab.sop.exception.route"
    _description = "SOP Exception Route"
    _order = "sop_id, sequence, id"

    sequence = fields.Integer(default=10)
    sop_id = fields.Many2one("lab.department.sop", required=True, ondelete="cascade", index=True)
    trigger_event = fields.Selection(
        [
            ("critical", "Critical Result"),
            ("delta_fail", "Delta Check Failed"),
            ("qc_reject", "QC Reject"),
            ("instrument_error", "Instrument Error"),
            ("specimen_issue", "Specimen Rejection"),
            ("retest_exceeded", "Retest Limit Exceeded"),
        ],
        required=True,
    )
    severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="major",
    )
    route_action = fields.Selection(
        [
            ("manual_review", "Manual Review"),
            ("ncr", "Create NCR"),
            ("retest", "Retest"),
            ("recollect", "Re-collect"),
            ("manager_approval", "Manager Approval"),
        ],
        default="manual_review",
    )
    owner_group_id = fields.Many2one("res.groups", string="Owning Group")
    sla_hours = fields.Integer(default=0)
    note = fields.Text()


class LabPermissionMatrix(models.Model):
    _name = "lab.permission.matrix"
    _description = "Laboratory Permission Matrix"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    group_id = fields.Many2one("res.groups", required=True, ondelete="cascade")
    workstation = fields.Selection(
        [
            ("accession", "Accession"),
            ("analytical", "Analytical"),
            ("review", "Review"),
            ("quality", "Quality"),
            ("integration", "Integration"),
            ("billing", "Billing"),
            ("portal", "Portal"),
        ],
        required=True,
    )
    can_view = fields.Boolean(default=True)
    can_create = fields.Boolean(default=False)
    can_edit = fields.Boolean(default=False)
    can_approve = fields.Boolean(default=False)
    can_release = fields.Boolean(default=False)
    can_administer = fields.Boolean(default=False)
    note = fields.Text()

    _group_workstation_uniq = models.Constraint(
        "unique(group_id, workstation)",
        "Matrix already exists for this group/workstation.",
    )


class LabServiceSopMixin(models.Model):
    _inherit = "lab.service"

    sop_id = fields.Many2one("lab.department.sop", string="Department SOP")
    retest_policy_id = fields.Many2one("lab.retest.policy", string="Retest Policy")


class LabSampleSopMixin(models.Model):
    _inherit = "lab.sample"

    sop_id = fields.Many2one("lab.department.sop", string="Applied SOP", readonly=True, tracking=True, copy=False)
    sop_step_code = fields.Char(string="Current SOP Step", readonly=True, copy=False)
    sop_exception_state = fields.Selection(
        [("normal", "Normal"), ("exception", "Exception"), ("escalated", "Escalated")],
        default="normal",
        readonly=True,
        copy=False,
    )

    def _sync_sop(self):
        sop_obj = self.env["lab.department.sop"]
        for rec in self:
            if rec.sop_id and rec.sop_id.state == "active":
                continue
            first_analysis = rec.analysis_ids[:1]
            sop = first_analysis.service_id.sop_id if first_analysis and first_analysis.service_id.sop_id else False
            if not sop:
                sop = sop_obj.find_best_sop(rec, analysis=first_analysis)
            if sop:
                first_step = sop.step_ids.sorted("sequence")[:1]
                rec.write({"sop_id": sop.id, "sop_step_code": first_step.step_code if first_step else False})

    def _update_sop_step_by_state(self):
        state_map = {
            "draft": "register",
            "received": "accession",
            "in_progress": "analysis",
            "to_verify": "verify",
            "verified": "authorize",
            "reported": "release",
        }
        for rec in self:
            if not rec.sop_id:
                continue
            code = state_map.get(rec.state)
            if code:
                rec.sop_step_code = code

    def action_receive(self):
        result = super().action_receive()
        self._sync_sop()
        self._update_sop_step_by_state()
        return result

    def action_start(self):
        result = super().action_start()
        self._sync_sop()
        self._update_sop_step_by_state()
        return result

    def action_mark_to_verify(self):
        result = super().action_mark_to_verify()
        self._update_sop_step_by_state()
        return result

    def action_verify(self):
        result = super().action_verify()
        self._update_sop_step_by_state()
        return result

    def action_release_report(self):
        result = super().action_release_report()
        self._update_sop_step_by_state()
        return result


class LabSampleAnalysisSopMixin(models.Model):
    _inherit = "lab.sample.analysis"

    def _resolve_retest_policy(self):
        self.ensure_one()
        if self.service_id.retest_policy_id and self.service_id.retest_policy_id.active:
            return self.service_id.retest_policy_id
        if self.sample_id.sop_id and self.sample_id.sop_id.retest_policy_id and self.sample_id.sop_id.retest_policy_id.active:
            return self.sample_id.sop_id.retest_policy_id
        policy = self.env["lab.retest.policy"].search(
            [("scope", "=", "department"), ("department", "=", self.department), ("active", "=", True)],
            limit=1,
        )
        if policy:
            return policy
        return False

    def _enforce_retest_policy(self):
        for rec in self:
            policy = rec._resolve_retest_policy()
            if not policy:
                continue
            if policy.scope == "service" and not policy.matches_analysis(rec):
                continue
            if len(rec.retest_ids) >= policy.max_retest_count:
                rec.sample_id.write({"sop_exception_state": "exception"})
                raise UserError(
                    _(
                        "Retest limit reached for %(service)s (policy %(policy)s)."
                    )
                    % {"service": rec.service_id.name, "policy": policy.name}
                )
            if policy.require_reason and not (rec.result_note or "").strip():
                raise UserError(_("Retest reason is required in Result Note before requesting retest."))
            if policy.cooldown_minutes > 0 and rec.create_date:
                cool_until = rec.create_date + timedelta(minutes=policy.cooldown_minutes)
                if fields.Datetime.now() < cool_until:
                    raise UserError(
                        _("Retest cooldown active until %s.") % fields.Datetime.to_string(cool_until)
                    )

    def action_request_retest(self):
        if self.env.context.get("skip_retest_policy_check"):
            return super().action_request_retest()
        self._enforce_retest_policy()
        result = super().action_request_retest()
        for rec in self:
            policy = rec._resolve_retest_policy()
            if not policy:
                continue
            reject_count = len(rec.retest_ids) + (1 if rec.state == "rejected" else 0)
            if policy.escalate_after_failures and reject_count >= policy.escalate_after_failures:
                rec.sample_id.write({"sop_exception_state": "escalated"})
                rec.sample_id._auto_create_nonconformance(
                    _("Retest escalation: %s") % rec.service_id.name,
                    _(
                        "Retest escalation reached for %(service)s under policy %(policy)s."
                    )
                    % {"service": rec.service_id.name, "policy": policy.name},
                    severity="major",
                    analysis=rec,
                )
                group = policy.escalation_group_id or self.env.ref(
                    "laboratory_management.group_lab_manager", raise_if_not_found=False
                )
                if group:
                    todo = self.env.ref("mail.mail_activity_data_todo")
                    model_id = self.env["ir.model"]._get_id("lab.sample")
                    for user in group.user_ids:
                        self.env["mail.activity"].create(
                            {
                                "activity_type_id": todo.id,
                                "user_id": user.id,
                                "res_model_id": model_id,
                                "res_id": rec.sample_id.id,
                                "summary": _("Retest escalation"),
                                "note": _("Please review escalated retest case for %s.") % rec.sample_id.name,
                            }
                        )
        return result
