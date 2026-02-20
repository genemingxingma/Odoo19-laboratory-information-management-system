from odoo import _, api, fields, models


DEPARTMENTS = [
    ("chemistry", "Clinical Chemistry"),
    ("hematology", "Hematology"),
    ("microbiology", "Microbiology"),
    ("immunology", "Immunology"),
    ("other", "Other"),
]

SAMPLE_TYPES = [
    ("blood", "Blood"),
    ("urine", "Urine"),
    ("stool", "Stool"),
    ("swab", "Swab"),
    ("serum", "Serum"),
    ("other", "Other"),
    ("all", "All"),
]

PRIORITIES = [
    ("routine", "Routine"),
    ("urgent", "Urgent"),
    ("stat", "STAT"),
    ("all", "All"),
]

REQUEST_TYPES = [
    ("individual", "Individual"),
    ("institution", "Institution"),
    ("all", "All"),
]

FASTING_RULES = [
    ("ignore", "Ignore"),
    ("required", "Fasting Required"),
    ("not_required", "Fasting Not Required"),
]

REQUEST_TIME_WINDOWS = [
    ("all", "All"),
    ("day", "Day Shift (08:00-17:59)"),
    ("night", "Night Shift (18:00-07:59)"),
]

TRIGGERS = [
    ("critical", "Critical Result"),
    ("delta_fail", "Delta Check Failed"),
    ("qc_reject", "QC Reject"),
    ("instrument_error", "Instrument Error"),
    ("specimen_issue", "Specimen Rejection"),
    ("retest_exceeded", "Retest Limit Exceeded"),
    ("manual_review_reject", "Manual Review Rejected"),
    ("other", "Other"),
]

SEVERITIES = [
    ("minor", "Minor"),
    ("major", "Major"),
    ("critical", "Critical"),
    ("all", "All"),
]

ACTIONS = [
    ("manual_review", "Manual Review"),
    ("retest", "Retest"),
    ("recollect", "Recollect"),
    ("escalate", "Escalate"),
    ("ncr", "Create NCR"),
    ("stop", "Stop"),
]


class LabSopWorkflowProfile(models.Model):
    _name = "lab.sop.workflow.profile"
    _description = "SOP Workflow Profile"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    department = fields.Selection(DEPARTMENTS, required=True)
    sample_type = fields.Selection(SAMPLE_TYPES, default="all", required=True)
    priority = fields.Selection(PRIORITIES, default="all", required=True)
    request_type = fields.Selection(REQUEST_TYPES, default="all", required=True)
    fasting_rule = fields.Selection(FASTING_RULES, default="ignore", required=True)
    request_time_window = fields.Selection(REQUEST_TIME_WINDOWS, default="all", required=True)

    client_required = fields.Boolean(default=False)
    client_tag_ids = fields.Many2many("res.partner.category", string="Client Tags")
    service_ids = fields.Many2many("lab.service", string="Service Scope")

    sop_id = fields.Many2one("lab.department.sop", required=True, ondelete="restrict")
    retest_strategy_id = fields.Many2one("lab.sop.retest.strategy", ondelete="set null")
    note = fields.Text()

    _workflow_profile_code_uniq = models.Constraint("unique(code)", "Workflow profile code must be unique.")

    def _sample_department(self, sample, analysis=False):
        self.ensure_one()
        if analysis and analysis.department:
            return analysis.department
        if sample.analysis_ids:
            return sample.analysis_ids[:1].department or "other"
        return "other"

    def _sample_type(self, sample, analysis=False):
        self.ensure_one()
        if analysis and analysis.sample_type:
            return analysis.sample_type
        if sample.analysis_ids:
            return sample.analysis_ids[:1].sample_type or "other"
        return "other"

    def _request_type(self, sample):
        self.ensure_one()
        if sample.request_id and sample.request_id.request_type:
            return sample.request_id.request_type
        return "individual"

    def _request_fasting_required(self, sample):
        self.ensure_one()
        return bool(sample.request_id.fasting_required) if sample.request_id else False

    def _request_hour(self, sample):
        self.ensure_one()
        request_dt = sample.request_id.requested_collection_date if sample.request_id else False
        dt = request_dt or sample.collection_date
        if not dt:
            return 12
        return fields.Datetime.to_datetime(dt).hour

    def _match_request_time_window(self, sample):
        self.ensure_one()
        if self.request_time_window == "all":
            return True
        hour = self._request_hour(sample)
        is_day = 8 <= hour < 18
        return is_day if self.request_time_window == "day" else not is_day

    def _matches(self, sample, analysis=False):
        self.ensure_one()
        if not self.active:
            return False

        dept = self._sample_department(sample, analysis=analysis)
        if dept != self.department:
            return False

        sample_type = self._sample_type(sample, analysis=analysis)
        if self.sample_type not in ("all", sample_type):
            return False

        if self.priority not in ("all", sample.priority):
            return False

        req_type = self._request_type(sample)
        if self.request_type not in ("all", req_type):
            return False

        fasting = self._request_fasting_required(sample)
        if self.fasting_rule == "required" and not fasting:
            return False
        if self.fasting_rule == "not_required" and fasting:
            return False

        if not self._match_request_time_window(sample):
            return False

        client = sample.client_id or (sample.request_id.client_partner_id if sample.request_id else False)
        if self.client_required and not client:
            return False

        if self.service_ids:
            if analysis and analysis.service_id and analysis.service_id not in self.service_ids:
                return False
            sample_services = sample.analysis_ids.mapped("service_id")
            if not (set(sample_services.ids) & set(self.service_ids.ids)):
                return False

        if self.client_tag_ids:
            if not client:
                return False
            if not (set(client.category_id.ids) & set(self.client_tag_ids.ids)):
                return False

        if self.sop_id.state != "active":
            return False
        return True

    @api.model
    def _select_for_sample(self, sample, analysis=False):
        if not sample:
            return False
        dept = analysis.department if analysis and analysis.department else (sample.analysis_ids[:1].department if sample.analysis_ids else "other")
        candidates = self.search([("active", "=", True), ("department", "=", dept or "other")], order="sequence asc, id asc")
        for row in candidates:
            if row._matches(sample, analysis=analysis):
                return row
        return False


class LabSampleWorkflowProfileMixin(models.Model):
    _inherit = "lab.sample"

    workflow_profile_id = fields.Many2one("lab.sop.workflow.profile", readonly=True, copy=False)
    workflow_route_note = fields.Text(readonly=True, copy=False)

    def _sync_sop(self):
        profile_obj = self.env["lab.sop.workflow.profile"]
        unresolved = self.browse()

        for rec in self:
            first_analysis = rec.analysis_ids[:1]
            profile = profile_obj._select_for_sample(rec, analysis=first_analysis)
            if not profile:
                unresolved |= rec
                continue

            first_step = profile.sop_id.step_ids.sorted("sequence")[:1]
            rec.write(
                {
                    "workflow_profile_id": profile.id,
                    "workflow_route_note": _("Workflow profile %(profile)s matched on %(date)s")
                    % {"profile": profile.code, "date": fields.Datetime.now()},
                    "sop_id": profile.sop_id.id,
                    "sop_step_code": first_step.step_code if first_step else False,
                }
            )

        for rec in unresolved:
            super(LabSampleWorkflowProfileMixin, rec)._sync_sop()


class LabSampleSopExecutionProfileMixin(models.Model):
    _inherit = "lab.sample"

    def _ensure_execution(self):
        super()._ensure_execution()
        for rec in self:
            if not rec.sop_execution_id or rec.sop_execution_id.retest_strategy_id:
                continue
            profile = rec.workflow_profile_id
            if profile and profile.retest_strategy_id and profile.retest_strategy_id.active:
                rec.sop_execution_id.retest_strategy_id = profile.retest_strategy_id.id


class LabSopDecisionThresholdProfile(models.Model):
    _name = "lab.sop.decision.threshold.profile"
    _description = "SOP Decision Threshold Profile"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)
    department = fields.Selection(DEPARTMENTS, required=True)

    min_critical_count = fields.Integer(default=0)
    min_out_of_range_count = fields.Integer(default=0)
    min_manual_review_count = fields.Integer(default=0)
    min_retest_count = fields.Integer(default=0)
    min_delta_abs = fields.Float(default=0.0)
    max_delta_abs = fields.Float(default=0.0, help="0 means no upper bound")
    note = fields.Text()

    _threshold_profile_code_uniq = models.Constraint("unique(code)", "Threshold profile code must be unique.")

    def _sample_analyses(self, execution):
        self.ensure_one()
        return execution.sample_id.analysis_ids

    def _critical_count(self, execution):
        self.ensure_one()
        return len(self._sample_analyses(execution).filtered(lambda x: x.is_critical))

    def _out_of_range_count(self, execution):
        self.ensure_one()
        return len(self._sample_analyses(execution).filtered(lambda x: x.result_flag in ("high", "low", "critical")))

    def _manual_review_count(self, execution):
        self.ensure_one()
        return len(self._sample_analyses(execution).filtered(lambda x: x.needs_manual_review))

    def _retest_count(self, execution):
        self.ensure_one()
        return len(self._sample_analyses(execution).filtered(lambda x: x.is_retest))

    def _delta_abs_max(self, execution):
        self.ensure_one()
        deltas = [abs(x.delta_check_value) for x in self._sample_analyses(execution) if x.delta_check_value not in (False, None)]
        return max(deltas) if deltas else 0.0

    def _matches_execution(self, execution):
        self.ensure_one()
        if not self.active:
            return False
        if execution.sop_id.department != self.department:
            return False
        if self._critical_count(execution) < self.min_critical_count:
            return False
        if self._out_of_range_count(execution) < self.min_out_of_range_count:
            return False
        if self._manual_review_count(execution) < self.min_manual_review_count:
            return False
        if self._retest_count(execution) < self.min_retest_count:
            return False
        delta_abs = self._delta_abs_max(execution)
        if self.min_delta_abs and delta_abs < self.min_delta_abs:
            return False
        if self.max_delta_abs and delta_abs > self.max_delta_abs:
            return False
        return True


class LabSopExceptionDecision(models.Model):
    _name = "lab.sop.exception.decision"
    _description = "SOP Exception Decision Matrix"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    department = fields.Selection(DEPARTMENTS, required=True)
    sample_type = fields.Selection(SAMPLE_TYPES, default="all", required=True)
    priority = fields.Selection(PRIORITIES, default="all", required=True)
    request_type = fields.Selection(REQUEST_TYPES, default="all", required=True)

    trigger = fields.Selection(TRIGGERS, required=True)
    severity = fields.Selection(SEVERITIES, default="all", required=True)

    min_retest_count = fields.Integer(default=0)
    max_retest_count = fields.Integer(default=0, help="0 means no upper bound")

    min_delta_abs = fields.Float(default=0.0)
    max_delta_abs = fields.Float(default=0.0, help="0 means no upper bound")
    require_critical = fields.Boolean(default=False)
    threshold_profile_id = fields.Many2one(
        "lab.sop.decision.threshold.profile",
        ondelete="set null",
        domain="[('department','=',department), ('active','=',True)]",
    )

    action = fields.Selection(ACTIONS, default="manual_review", required=True)
    route_group_id = fields.Many2one("res.groups")
    ncr_severity = fields.Selection([("minor", "Minor"), ("major", "Major"), ("critical", "Critical")], default="major")
    stop_execution = fields.Boolean(default=False)
    note = fields.Text()

    _exception_decision_code_uniq = models.Constraint("unique(code)", "Exception decision code must be unique.")

    def _severity_guess(self, execution):
        self.ensure_one()
        if execution.sample_id.analysis_ids.filtered(lambda x: x.is_critical):
            return "critical"
        if execution.sample_id.analysis_ids.filtered(lambda x: x.result_flag in ("high", "low")):
            return "major"
        return "minor"

    def _max_delta_abs(self, execution):
        self.ensure_one()
        deltas = [abs(x.delta_check_value) for x in execution.sample_id.analysis_ids if x.delta_check_value not in (False, None)]
        return max(deltas) if deltas else 0.0

    def _retest_count(self, execution):
        self.ensure_one()
        return len(execution.sample_id.analysis_ids.filtered(lambda x: x.is_retest))

    def _matches(self, execution, trigger, severity=False):
        self.ensure_one()
        if not self.active:
            return False
        sample = execution.sample_id
        if self.department != execution.sop_id.department:
            return False

        sample_type = sample.analysis_ids[:1].sample_type if sample.analysis_ids else "other"
        if self.sample_type not in ("all", sample_type):
            return False
        if self.priority not in ("all", sample.priority):
            return False

        req_type = sample.request_id.request_type if sample.request_id else "individual"
        if self.request_type not in ("all", req_type):
            return False

        if self.trigger != trigger:
            return False

        sev = severity or self._severity_guess(execution)
        if self.severity not in ("all", sev):
            return False

        retest_count = self._retest_count(execution)
        if retest_count < self.min_retest_count:
            return False
        if self.max_retest_count and retest_count > self.max_retest_count:
            return False

        delta_abs = self._max_delta_abs(execution)
        if self.min_delta_abs and delta_abs < self.min_delta_abs:
            return False
        if self.max_delta_abs and delta_abs > self.max_delta_abs:
            return False

        if self.require_critical and not sample.analysis_ids.filtered(lambda x: x.is_critical):
            return False

        if self.threshold_profile_id and not self.threshold_profile_id._matches_execution(execution):
            return False

        return True

    @api.model
    def _select_for_execution(self, execution, trigger, severity=False):
        if not execution:
            return False
        rows = self.search(
            [
                ("active", "=", True),
                ("department", "=", execution.sop_id.department),
                ("trigger", "=", trigger),
            ],
            order="sequence asc, id asc",
        )
        for row in rows:
            if row._matches(execution, trigger, severity=severity):
                return row
        return False


class LabSopExceptionDecisionRun(models.Model):
    _name = "lab.sop.exception.decision.run"
    _description = "SOP Exception Decision Run"
    _order = "id desc"

    execution_id = fields.Many2one("lab.sop.execution", required=True, ondelete="cascade", index=True)
    sample_id = fields.Many2one(related="execution_id.sample_id", store=True)
    trigger = fields.Selection(TRIGGERS, required=True)
    severity = fields.Selection(SEVERITIES[:-1], required=True)

    decision_id = fields.Many2one("lab.sop.exception.decision", ondelete="set null")
    matched = fields.Boolean(default=False)
    result_action = fields.Selection(ACTIONS, default="manual_review")
    note = fields.Text()
    run_time = fields.Datetime(default=fields.Datetime.now, required=True)


class LabSopExecutionDecisionMixin(models.Model):
    _inherit = "lab.sop.execution"

    decision_run_ids = fields.One2many("lab.sop.exception.decision.run", "execution_id", string="Decision Runs")
    decision_run_count = fields.Integer(compute="_compute_decision_run_count")

    def _compute_decision_run_count(self):
        run_obj = self.env["lab.sop.exception.decision.run"]
        for rec in self:
            rec.decision_run_count = run_obj.search_count([("execution_id", "=", rec.id)])

    def _current_severity(self):
        self.ensure_one()
        if self.sample_id.analysis_ids.filtered(lambda x: x.is_critical):
            return "critical"
        if self.sample_id.analysis_ids.filtered(lambda x: x.result_flag in ("high", "low")):
            return "major"
        return "minor"

    def _log_decision_run(self, trigger, severity, decision=False, action="manual_review", matched=False, note=False):
        self.ensure_one()
        self.env["lab.sop.exception.decision.run"].create(
            {
                "execution_id": self.id,
                "trigger": trigger,
                "severity": severity,
                "decision_id": decision.id if decision else False,
                "matched": matched,
                "result_action": action,
                "note": note or "",
            }
        )

    def _route_ncr(self, reason=False, decision=False):
        self.ensure_one()
        severity = decision.ncr_severity if decision else "major"
        self.sample_id._auto_create_nonconformance(
            title=_("SOP NCR for sample %s") % self.sample_id.name,
            description=reason or _("Created by SOP decision matrix."),
            severity=severity,
        )
        self.sample_id.write({"sop_exception_state": "escalated"})
        self._log_event("route_escalate", reason or _("Routed to NCR."))
        group = decision.route_group_id if decision and decision.route_group_id else self.env.ref(
            "laboratory_management.group_lab_manager", raise_if_not_found=False
        )
        if group:
            self._schedule_owner_activity(
                group=group,
                summary=_("SOP NCR created"),
                note=reason or _("SOP decision matrix created an NCR."),
            )

    def action_open_decision_runs(self):
        self.ensure_one()
        return {
            "name": _("Decision Runs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sop.exception.decision.run",
            "view_mode": "list,form",
            "domain": [("execution_id", "=", self.id)],
        }

    def _apply_exception_route(self, trigger="other", reason=False):
        decision_obj = self.env["lab.sop.exception.decision"]
        handled = self.browse()

        for rec in self:
            severity = rec._current_severity()
            decision = decision_obj._select_for_execution(rec, trigger=trigger, severity=severity)
            if not decision:
                rec._log_decision_run(
                    trigger=trigger,
                    severity=severity,
                    action="manual_review",
                    matched=False,
                    note=_("No decision matched, fallback to strategy."),
                )
                continue

            handled |= rec
            action = decision.action
            rec._log_decision_run(
                trigger=trigger,
                severity=severity,
                decision=decision,
                action=action,
                matched=True,
                note=reason or decision.note,
            )

            if action == "retest":
                rec._route_retest(reason=reason or decision.note, strategy=rec._resolve_strategy())
            elif action == "recollect":
                rec._route_recollect(reason=reason or decision.note, strategy=rec._resolve_strategy())
            elif action == "manual_review":
                rec._route_manual_review(reason=reason or decision.note, strategy=rec._resolve_strategy())
            elif action == "escalate":
                rec._route_escalate(reason=reason or decision.note, route_group=decision.route_group_id)
            elif action == "ncr":
                rec._route_ncr(reason=reason or decision.note, decision=decision)
            else:
                rec._route_stop(reason=reason or decision.note)

            if decision.stop_execution:
                rec.state = "exception"

        for rec in self - handled:
            super(LabSopExecutionDecisionMixin, rec)._apply_exception_route(trigger=trigger, reason=reason)
