from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabSopRetestStrategy(models.Model):
    _name = "lab.sop.retest.strategy"
    _description = "SOP Retest Strategy"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
        required=True,
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
    max_total_attempts = fields.Integer(default=2, required=True)
    cooldown_minutes = fields.Integer(default=0)
    recollect_after_attempt = fields.Integer(default=0)
    escalate_after_attempt = fields.Integer(default=0)
    owner_group_id = fields.Many2one("res.groups")
    line_ids = fields.One2many("lab.sop.retest.strategy.line", "strategy_id", string="Rules")
    rule_warning_count = fields.Integer(compute="_compute_rule_warning_count")
    active = fields.Boolean(default=True)
    note = fields.Text()

    _retest_strategy_code_uniq = models.Constraint("unique(code)", "Retest strategy code must be unique.")

    @api.constrains("max_total_attempts", "cooldown_minutes", "recollect_after_attempt", "escalate_after_attempt")
    def _check_limits(self):
        for rec in self:
            if rec.max_total_attempts < 1:
                raise ValidationError(_("Max total attempts must be >= 1."))
            if rec.cooldown_minutes < 0 or rec.recollect_after_attempt < 0 or rec.escalate_after_attempt < 0:
                raise ValidationError(_("Retest strategy numeric values must be non-negative."))

    @api.depends("line_ids.has_overlap")
    def _compute_rule_warning_count(self):
        for rec in self:
            rec.rule_warning_count = len(rec.line_ids.filtered("has_overlap"))

    def action_validate_rule_matrix(self):
        self.ensure_one()
        warning_count = self.rule_warning_count
        msg = (
            _("Rule matrix check completed: %(count)s overlapping rule(s) detected.")
            % {"count": warning_count}
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Retest Strategy Validation"),
                "message": msg,
                "sticky": False,
                "type": "warning" if warning_count else "success",
            },
        }


class LabSopRetestStrategyLine(models.Model):
    _name = "lab.sop.retest.strategy.line"
    _description = "SOP Retest Strategy Rule"
    _order = "strategy_id, sequence, id"

    sequence = fields.Integer(default=10)
    strategy_id = fields.Many2one("lab.sop.retest.strategy", required=True, ondelete="cascade", index=True)
    trigger = fields.Selection(
        [
            ("critical", "Critical Result"),
            ("delta_fail", "Delta Check Failed"),
            ("qc_reject", "QC Reject"),
            ("instrument_error", "Instrument Error"),
            ("manual_review_reject", "Manual Review Rejected"),
            ("other", "Other"),
        ],
        required=True,
    )
    severity = fields.Selection(
        [("all", "All"), ("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="all",
        required=True,
    )
    action = fields.Selection(
        [
            ("retest", "Retest"),
            ("recollect", "Recollect"),
            ("manual_review", "Manual Review"),
            ("escalate", "Escalate"),
            ("stop", "Stop"),
        ],
        default="retest",
        required=True,
    )
    min_attempt = fields.Integer(default=0, help="Minimum current retest count to enable this rule.")
    max_attempt = fields.Integer(default=0, help="0 means no per-rule cap")
    service_ids = fields.Many2many("lab.service", string="Service Scope")
    require_reason = fields.Boolean(default=True)
    route_to_group_id = fields.Many2one("res.groups")
    note = fields.Text()
    has_overlap = fields.Boolean(compute="_compute_overlap_status")
    overlap_note = fields.Char(compute="_compute_overlap_status")

    @api.constrains("min_attempt", "max_attempt")
    def _check_attempt_range(self):
        for rec in self:
            if rec.min_attempt < 0 or rec.max_attempt < 0:
                raise ValidationError(_("Retest strategy rule attempt values must be non-negative."))
            if rec.max_attempt and rec.max_attempt < rec.min_attempt:
                raise ValidationError(_("Rule max attempt must be >= min attempt."))

    @api.constrains("strategy_id", "trigger", "severity", "min_attempt", "max_attempt", "service_ids")
    def _check_duplicate_rule(self):
        for rec in self:
            duplicates = rec.strategy_id.line_ids.filtered(
                lambda x: x.id != rec.id
                and x.trigger == rec.trigger
                and x.severity == rec.severity
                and (x.min_attempt or 0) == (rec.min_attempt or 0)
                and (x.max_attempt or 0) == (rec.max_attempt or 0)
                and set(x.service_ids.ids) == set(rec.service_ids.ids)
            )
            if duplicates:
                raise ValidationError(_("Duplicate retest strategy rule detected in the same strategy."))

    @api.depends("strategy_id.line_ids", "trigger", "severity", "min_attempt", "max_attempt", "service_ids")
    def _compute_overlap_status(self):
        for rec in self:
            rec.has_overlap = False
            rec.overlap_note = False
            if not rec.strategy_id:
                continue
            prior_rules = rec.strategy_id.line_ids.filtered(lambda x: x.id != rec.id and x.sequence <= rec.sequence).sorted(
                key=lambda x: (x.sequence, x.id)
            )
            for prior in prior_rules:
                if not rec._is_overlap_with(prior):
                    continue
                rec.has_overlap = True
                rec.overlap_note = _(
                    "Potential overlap with rule #%s (same trigger/attempt/service scope)."
                ) % prior.id
                break

    def _severity_set(self):
        self.ensure_one()
        if self.severity == "all":
            return {"minor", "major", "critical"}
        return {self.severity}

    def _attempt_range(self):
        self.ensure_one()
        low = self.min_attempt or 0
        high = self.max_attempt if self.max_attempt else 999999
        return low, high

    def _service_scope_is_overlap(self, other):
        self.ensure_one()
        if not self.service_ids or not other.service_ids:
            return True
        return bool(set(self.service_ids.ids) & set(other.service_ids.ids))

    def _is_overlap_with(self, other):
        self.ensure_one()
        if self.trigger != other.trigger:
            return False
        if not (self._severity_set() & other._severity_set()):
            return False
        s_low, s_high = self._attempt_range()
        o_low, o_high = other._attempt_range()
        if s_low > o_high or o_low > s_high:
            return False
        if not self._service_scope_is_overlap(other):
            return False
        return True


class LabSopExecution(models.Model):
    _name = "lab.sop.execution"
    _description = "SOP Execution"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True)
    sop_id = fields.Many2one("lab.department.sop", required=True, ondelete="restrict", index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("exception", "Exception"),
            ("completed", "Completed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )
    current_step_id = fields.Many2one("lab.sop.execution.step", readonly=True)
    step_ids = fields.One2many("lab.sop.execution.step", "execution_id", string="Execution Steps")
    event_ids = fields.One2many("lab.sop.execution.event", "execution_id", string="Execution Events")
    retest_strategy_id = fields.Many2one("lab.sop.retest.strategy", string="Retest Strategy")
    total_steps = fields.Integer(compute="_compute_progress")
    done_steps = fields.Integer(compute="_compute_progress")
    failed_steps = fields.Integer(compute="_compute_progress")
    completion_rate = fields.Float(compute="_compute_progress")
    exception_reason = fields.Text()

    _sample_uniq = models.Constraint("unique(sample_id)", "A sample can only have one active SOP execution.")

    @api.depends("step_ids.state")
    def _compute_progress(self):
        for rec in self:
            rec.total_steps = len(rec.step_ids)
            rec.done_steps = len(rec.step_ids.filtered(lambda x: x.state == "done"))
            rec.failed_steps = len(rec.step_ids.filtered(lambda x: x.state == "failed"))
            rec.completion_rate = (100.0 * rec.done_steps / rec.total_steps) if rec.total_steps else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.audit") or "New"
        records = super().create(vals_list)
        for rec in records:
            rec._initialize_steps()
        return records

    def _initialize_steps(self):
        for rec in self:
            if rec.step_ids:
                continue
            lines = []
            for step in rec.sop_id.step_ids.sorted("sequence"):
                lines.append(
                    (
                        0,
                        0,
                        {
                            "step_id": step.id,
                            "sequence": step.sequence,
                            "step_code": step.step_code,
                            "name": step.name,
                            "workstation_role": step.workstation_role,
                            "required": step.required,
                            "on_fail_action": step.on_fail_action,
                            "max_hours_from_prev": step.max_hours_from_prev,
                            "state": "waiting",
                        },
                    )
                )
            if lines:
                rec.write({"step_ids": lines})
                first = rec.step_ids.sorted("sequence")[:1]
                if first:
                    first.state = "ready"
                    rec.current_step_id = first.id

    def action_start(self):
        for rec in self:
            if rec.state not in ("draft", "exception"):
                continue
            if not rec.step_ids:
                rec._initialize_steps()
            rec.state = "running"
            rec._log_event("start", _("SOP execution started."))
        return True

    def _next_step(self):
        self.ensure_one()
        if not self.current_step_id:
            return False
        candidates = self.step_ids.sorted("sequence").filtered(lambda x: x.sequence > self.current_step_id.sequence)
        return candidates[:1] if candidates else False

    def action_complete_current_step(self, note=False):
        for rec in self:
            if rec.state not in ("running", "exception"):
                continue
            step = rec.current_step_id
            if not step:
                continue
            step._mark_done(note=note)
            nxt = rec._next_step()
            if nxt:
                nxt.state = "ready"
                rec.current_step_id = nxt.id
                rec.state = "running"
                rec._log_event("step_done", _("Step %(step)s completed, moved to %(next)s.") % {
                    "step": step.step_code,
                    "next": nxt.step_code,
                })
            else:
                rec.current_step_id = False
                rec.state = "completed"
                rec._log_event("complete", _("SOP execution completed."))
        return True

    def action_fail_current_step(self, reason=False, trigger=False):
        for rec in self:
            if rec.state not in ("running", "exception"):
                continue
            step = rec.current_step_id
            if not step:
                continue
            step._mark_failed(reason=reason)
            rec.state = "exception"
            rec.exception_reason = reason or _("Step failed without reason")
            rec._log_event("step_failed", _("Step %(step)s failed: %(reason)s") % {
                "step": step.step_code,
                "reason": rec.exception_reason,
            })
            rec._apply_exception_route(trigger=trigger or "other", reason=reason)
        return True

    def _resolve_strategy(self):
        self.ensure_one()
        if self.retest_strategy_id and self.retest_strategy_id.active:
            return self.retest_strategy_id
        department = self.sop_id.department
        sample_type = self.sop_id.sample_type or "other"
        strategy = self.env["lab.sop.retest.strategy"].search(
            [
                ("active", "=", True),
                ("department", "=", department),
                "|",
                ("sample_type", "=", sample_type),
                ("sample_type", "=", "other"),
            ],
            order="sample_type desc, sequence asc, id asc",
            limit=1,
        )
        return strategy

    def _apply_exception_route(self, trigger="other", reason=False):
        for rec in self:
            strategy = rec._resolve_strategy()
            if not strategy:
                rec._schedule_owner_activity(
                    group=self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False),
                    summary=_("SOP exception pending"),
                    note=reason or _("SOP exception occurred and no strategy matched."),
                )
                continue

            total_retests = len(
                rec.sample_id.analysis_ids.filtered(lambda x: x.is_retest)
            )
            action = "manual_review"
            route_group = strategy.owner_group_id
            line = rec._select_strategy_line(strategy, trigger=trigger, total_retests=total_retests)
            if line:
                action = line.action
                if line.route_to_group_id:
                    route_group = line.route_to_group_id
                if line.max_attempt and total_retests >= line.max_attempt:
                    action = "escalate"

            if strategy.escalate_after_attempt and total_retests >= strategy.escalate_after_attempt:
                action = "escalate"
            if strategy.recollect_after_attempt and total_retests >= strategy.recollect_after_attempt:
                action = "recollect"
            if total_retests >= strategy.max_total_attempts:
                action = "stop"

            if action == "retest":
                rec._route_retest(reason=reason, strategy=strategy)
            elif action == "recollect":
                rec._route_recollect(reason=reason, strategy=strategy)
            elif action == "manual_review":
                rec._route_manual_review(reason=reason, strategy=strategy)
            elif action == "escalate":
                rec._route_escalate(reason=reason, route_group=route_group)
            else:
                rec._route_stop(reason=reason)

    def _current_exception_severity(self):
        self.ensure_one()
        analyses = self.sample_id.analysis_ids
        if analyses.filtered(lambda x: x.is_critical):
            return "critical"
        if analyses.filtered(lambda x: x.result_flag in ("high", "low")):
            return "major"
        return "minor"

    def _select_strategy_line(self, strategy, *, trigger, total_retests):
        self.ensure_one()
        severity = self._current_exception_severity()
        sample_service_ids = set(self.sample_id.analysis_ids.mapped("service_id").ids)
        candidates = strategy.line_ids.sorted("sequence")
        for line in candidates:
            if line.trigger != trigger:
                continue
            if line.severity not in ("all", severity):
                continue
            if total_retests < (line.min_attempt or 0):
                continue
            if line.service_ids and not (sample_service_ids & set(line.service_ids.ids)):
                continue
            return line
        return False

    def _schedule_owner_activity(self, group, summary, note):
        self.ensure_one()
        if not group:
            return
        todo = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("lab.sop.execution")
        for user in group.user_ids:
            self.env["mail.activity"].create(
                {
                    "activity_type_id": todo.id,
                    "user_id": user.id,
                    "res_model_id": model_id,
                    "res_id": self.id,
                    "summary": summary,
                    "note": note,
                }
            )

    def _route_retest(self, reason=False, strategy=False):
        self.ensure_one()
        target_lines = self.sample_id.analysis_ids.filtered(lambda x: x.state in ("done", "rejected", "verified"))
        if not target_lines:
            self._route_manual_review(reason=reason or _("No analysis line available for retest."), strategy=strategy)
            return
        for line in target_lines[:1]:
            if strategy and strategy.cooldown_minutes > 0 and line.create_date:
                cool_until = line.create_date + timedelta(minutes=strategy.cooldown_minutes)
                if fields.Datetime.now() < cool_until:
                    self._route_manual_review(
                        reason=_("Retest cooldown active until %s") % fields.Datetime.to_string(cool_until),
                        strategy=strategy,
                    )
                    return
            line.result_note = reason or _("Retest requested by SOP exception route")
            line.with_context(
                skip_sop_execution_route=True,
                skip_retest_policy_check=True,
            ).action_request_retest()
        self._log_event("route_retest", reason or _("Routed to retest."))

    def _route_recollect(self, reason=False, strategy=False):
        self.ensure_one()
        self.sample_id.state = "draft"
        self.sample_id._log_timeline("recollect", reason or _("SOP requested recollection."))
        self.sample_id._create_signoff("recollect", reason or _("SOP requested recollection."))
        self._log_event("route_recollect", reason or _("Routed to recollection."))
        if strategy and strategy.owner_group_id:
            self._schedule_owner_activity(
                group=strategy.owner_group_id,
                summary=_("Sample recollection needed"),
                note=reason or _("SOP strategy requested recollection."),
            )

    def _route_manual_review(self, reason=False, strategy=False):
        self.ensure_one()
        lines = self.sample_id.analysis_ids.filtered(lambda x: x.state in ("assigned", "done", "verified"))
        lines.write({"needs_manual_review": True})
        self.sample_id._log_timeline("to_verify", reason or _("SOP routed to manual review."))
        self._log_event("route_manual_review", reason or _("Routed to manual review."))
        group = strategy.owner_group_id if strategy and strategy.owner_group_id else self.env.ref(
            "laboratory_management.group_lab_reviewer", raise_if_not_found=False
        )
        if group:
            self._schedule_owner_activity(
                group=group,
                summary=_("Manual review required"),
                note=reason or _("SOP exception routed this sample to manual review."),
            )

    def _route_escalate(self, reason=False, route_group=False):
        self.ensure_one()
        self.sample_id.write({"sop_exception_state": "escalated"})
        self.sample_id._auto_create_nonconformance(
            title=_("SOP escalation for sample %s") % self.sample_id.name,
            description=reason or _("Escalated by SOP execution route."),
            severity="major",
        )
        self._log_event("route_escalate", reason or _("Routed to escalation."))
        group = route_group or self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
        if group:
            self._schedule_owner_activity(
                group=group,
                summary=_("SOP escalation"),
                note=reason or _("SOP exception escalated this sample."),
            )

    def _route_stop(self, reason=False):
        self.ensure_one()
        self.state = "exception"
        self.sample_id.write({"sop_exception_state": "exception"})
        self._log_event("route_stop", reason or _("Execution stopped by strategy."))

    def _log_event(self, event_type, note):
        self.ensure_one()
        self.env["lab.sop.execution.event"].create(
            {
                "execution_id": self.id,
                "event_type": event_type,
                "event_time": fields.Datetime.now(),
                "user_id": self.env.user.id,
                "note": note,
            }
        )


class LabSopExecutionStep(models.Model):
    _name = "lab.sop.execution.step"
    _description = "SOP Execution Step"
    _order = "execution_id, sequence, id"

    execution_id = fields.Many2one("lab.sop.execution", required=True, ondelete="cascade", index=True)
    step_id = fields.Many2one("lab.department.sop.step", ondelete="set null")
    sequence = fields.Integer(default=10)
    step_code = fields.Char(required=True)
    name = fields.Char(required=True)
    workstation_role = fields.Selection(
        [
            ("reception", "Reception"),
            ("analyst", "Analyst"),
            ("reviewer", "Reviewer"),
            ("manager", "Manager"),
        ],
        required=True,
    )
    required = fields.Boolean(default=True)
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
    max_hours_from_prev = fields.Integer(default=0)
    state = fields.Selection(
        [
            ("waiting", "Waiting"),
            ("ready", "Ready"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        default="waiting",
    )
    due_date = fields.Datetime()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    owner_user_id = fields.Many2one("res.users")
    note = fields.Text()

    @api.constrains("max_hours_from_prev")
    def _check_max_hours(self):
        for rec in self:
            if rec.max_hours_from_prev < 0:
                raise ValidationError(_("Max hours from previous step must be >= 0."))

    def _mark_done(self, note=False):
        for rec in self:
            now = fields.Datetime.now()
            rec.write(
                {
                    "state": "done",
                    "finished_at": now,
                    "owner_user_id": rec.owner_user_id.id or self.env.user.id,
                    "note": note or rec.note,
                }
            )

    def _mark_failed(self, reason=False):
        for rec in self:
            rec.write(
                {
                    "state": "failed",
                    "finished_at": fields.Datetime.now(),
                    "owner_user_id": rec.owner_user_id.id or self.env.user.id,
                    "note": reason or rec.note,
                }
            )

    def action_claim(self):
        for rec in self:
            if rec.state not in ("ready", "running"):
                continue
            rec.write(
                {
                    "state": "running",
                    "started_at": rec.started_at or fields.Datetime.now(),
                    "owner_user_id": self.env.user.id,
                }
            )

    def action_skip(self):
        for rec in self:
            if rec.required:
                raise UserError(_("Required step cannot be skipped."))
            rec.write({"state": "skipped", "finished_at": fields.Datetime.now(), "owner_user_id": self.env.user.id})


class LabSopExecutionEvent(models.Model):
    _name = "lab.sop.execution.event"
    _description = "SOP Execution Event"
    _order = "event_time desc, id desc"

    execution_id = fields.Many2one("lab.sop.execution", required=True, ondelete="cascade", index=True)
    sample_id = fields.Many2one(related="execution_id.sample_id", store=True)
    event_type = fields.Selection(
        [
            ("start", "Start"),
            ("step_done", "Step Done"),
            ("step_failed", "Step Failed"),
            ("route_retest", "Route Retest"),
            ("route_recollect", "Route Recollect"),
            ("route_manual_review", "Route Manual Review"),
            ("route_escalate", "Route Escalate"),
            ("route_stop", "Route Stop"),
            ("complete", "Complete"),
            ("permission_denied", "Permission Denied"),
        ],
        required=True,
    )
    event_time = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", required=True)
    note = fields.Text(required=True)


class LabPermissionMatrixRuntimeMixin(models.AbstractModel):
    _name = "lab.permission.matrix.runtime.mixin"
    _description = "Permission Matrix Runtime Mixin"

    @api.model
    def _matrix_action_to_field(self, action):
        mapping = {
            "view": "can_view",
            "create": "can_create",
            "edit": "can_edit",
            "approve": "can_approve",
            "release": "can_release",
            "admin": "can_administer",
        }
        return mapping.get(action)

    @api.model
    def _check_matrix_permission(self, workstation, action, user=False):
        user = user or self.env.user
        field_name = self._matrix_action_to_field(action)
        if not field_name:
            raise UserError(_("Unknown permission action: %s") % action)
        rows = self.env["lab.permission.matrix"].search(
            [
                ("workstation", "=", workstation),
                ("group_id", "in", user.group_ids.ids),
            ]
        )
        if not rows:
            return True
        return bool(rows.filtered(lambda x: getattr(x, field_name)))


class LabSampleSopExecutionMixin(models.Model):
    _inherit = "lab.sample"

    sop_execution_id = fields.Many2one("lab.sop.execution", copy=False, readonly=True)

    def _ensure_execution(self):
        for rec in self:
            if rec.sop_execution_id or not rec.sop_id:
                continue
            execution = self.env["lab.sop.execution"].create(
                {
                    "sample_id": rec.id,
                    "sop_id": rec.sop_id.id,
                }
            )
            rec.sop_execution_id = execution.id

    def action_receive(self):
        result = super().action_receive()
        for rec in self:
            rec._ensure_execution()
            if rec.sop_execution_id:
                rec.sop_execution_id.action_start()
        return result

    def action_verify(self):
        runtime = self.env["lab.permission.matrix.runtime.mixin"]
        for rec in self:
            allowed = runtime._check_matrix_permission("review", "approve")
            if not allowed:
                if rec.sop_execution_id:
                    rec.sop_execution_id._log_event(
                        "permission_denied",
                        _("User %(user)s denied verify/approve on sample %(sample)s")
                        % {"user": self.env.user.display_name, "sample": rec.name},
                    )
                raise UserError(_("You do not have permission to verify results."))
        result = super().action_verify()
        for rec in self:
            if rec.sop_execution_id and rec.sop_execution_id.state == "running":
                rec.sop_execution_id.action_complete_current_step(note=_("Sample verified"))
        return result

    def action_release_report(self):
        runtime = self.env["lab.permission.matrix.runtime.mixin"]
        for rec in self:
            allowed = runtime._check_matrix_permission("review", "release")
            if not allowed:
                if rec.sop_execution_id:
                    rec.sop_execution_id._log_event(
                        "permission_denied",
                        _("User %(user)s denied release on sample %(sample)s")
                        % {"user": self.env.user.display_name, "sample": rec.name},
                    )
                raise UserError(_("You do not have permission to release reports."))
        result = super().action_release_report()
        for rec in self:
            if rec.sop_execution_id and rec.sop_execution_id.state == "running":
                rec.sop_execution_id.action_complete_current_step(note=_("Report released"))
        return result


class LabSampleAnalysisSopExecutionMixin(models.Model):
    _inherit = "lab.sample.analysis"

    def action_request_retest(self):
        if self.env.context.get("skip_sop_execution_route"):
            return super().action_request_retest()
        for rec in self:
            if rec.sample_id.sop_execution_id and rec.sample_id.sop_execution_id.state in ("running", "exception"):
                rec.sample_id.sop_execution_id.action_fail_current_step(
                    reason=_("Retest requested for %(service)s") % {"service": rec.service_id.name},
                    trigger="manual_review_reject",
                )
        return super().action_request_retest()


class LabSopExecutionDashboardWizard(models.TransientModel):
    _name = "lab.sop.execution.dashboard.wizard"
    _description = "SOP Execution Dashboard"

    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
        default="chemistry",
        required=True,
    )
    period_days = fields.Integer(default=30, required=True)
    total_execution = fields.Integer(readonly=True)
    running_execution = fields.Integer(readonly=True)
    exception_execution = fields.Integer(readonly=True)
    completed_execution = fields.Integer(readonly=True)
    avg_completion_rate = fields.Float(readonly=True)
    avg_step_duration_minutes = fields.Float(readonly=True)
    manual_review_routed = fields.Integer(readonly=True)
    escalated_count = fields.Integer(readonly=True)

    @api.model
    def _compute_metrics_values(self, department, period_days):
        dt_from = fields.Datetime.now() - timedelta(days=period_days)
        domain = [
            ("create_date", ">=", fields.Datetime.to_string(dt_from)),
            ("sop_id.department", "=", department),
        ]
        executions = self.env["lab.sop.execution"].search(domain)
        step_obj = self.env["lab.sop.execution.step"]
        done_steps = step_obj.search([
            ("execution_id", "in", executions.ids),
            ("state", "=", "done"),
            ("started_at", "!=", False),
            ("finished_at", "!=", False),
        ])
        durations = []
        for step in done_steps:
            durations.append((step.finished_at - step.started_at).total_seconds() / 60.0)
        avg_rate = sum(executions.mapped("completion_rate")) / len(executions) if executions else 0.0
        return {
            "total_execution": len(executions),
            "running_execution": len(executions.filtered(lambda x: x.state == "running")),
            "exception_execution": len(executions.filtered(lambda x: x.state == "exception")),
            "completed_execution": len(executions.filtered(lambda x: x.state == "completed")),
            "avg_completion_rate": avg_rate,
            "avg_step_duration_minutes": (sum(durations) / len(durations)) if durations else 0.0,
            "manual_review_routed": self.env["lab.sop.execution.event"].search_count([
                ("execution_id", "in", executions.ids),
                ("event_type", "=", "route_manual_review"),
            ]),
            "escalated_count": self.env["lab.sop.execution.event"].search_count([
                ("execution_id", "in", executions.ids),
                ("event_type", "=", "route_escalate"),
            ]),
        }

    def _compute_metrics(self):
        self.ensure_one()
        return self._compute_metrics_values(self.department, self.period_days)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        department = vals.get("department") or "chemistry"
        period_days = vals.get("period_days") or 30
        metrics = self._compute_metrics_values(department, period_days)
        vals.update({k: v for k, v in metrics.items() if k in fields_list})
        return vals

    def action_refresh(self):
        for rec in self:
            rec.write(rec._compute_metrics())
        return True

    def action_open_executions(self):
        self.ensure_one()
        dt_from = fields.Datetime.now() - timedelta(days=self.period_days)
        return {
            "name": _("SOP Executions"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sop.execution",
            "view_mode": "list,form",
            "domain": [
                ("create_date", ">=", fields.Datetime.to_string(dt_from)),
                ("sop_id.department", "=", self.department),
            ],
        }
