import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


TASK_STATES = [
    ("new", "New"),
    ("assigned", "Assigned"),
    ("in_progress", "In Progress"),
    ("blocked", "Blocked"),
    ("done", "Done"),
    ("cancel", "Cancelled"),
    ("overdue", "Overdue"),
]

TASK_PRIORITIES = [
    ("routine", "Routine"),
    ("urgent", "Urgent"),
    ("stat", "STAT"),
]

WORKSTATIONS = [
    ("accession", "Accession"),
    ("analysis", "Analysis"),
    ("review", "Review"),
    ("quality", "Quality"),
    ("interface", "Interface"),
    ("billing", "Billing"),
]

DEPARTMENTS = [
    ("chemistry", "Clinical Chemistry"),
    ("hematology", "Hematology"),
    ("microbiology", "Microbiology"),
    ("immunology", "Immunology"),
    ("other", "Other"),
]


class LabTaskSlaPolicy(models.Model):
    _name = "lab.task.sla.policy"
    _description = "Task SLA Policy"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    department = fields.Selection(DEPARTMENTS, required=True)
    workstation = fields.Selection(WORKSTATIONS, required=True)
    priority = fields.Selection(TASK_PRIORITIES + [("all", "All")], default="all", required=True)
    sla_hours = fields.Integer(default=24, required=True)
    escalation_group_id = fields.Many2one("res.groups")
    auto_assign_group_id = fields.Many2one("res.groups")
    active = fields.Boolean(default=True)
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "Task SLA policy code must be unique.")

    @api.constrains("sla_hours")
    def _check_sla(self):
        for rec in self:
            if rec.sla_hours < 0:
                raise ValidationError(_("SLA hours must be >= 0."))


class LabWorkstationTask(models.Model):
    _name = "lab.workstation.task"
    _description = "Workstation Task"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    title = fields.Char(required=True)
    description = fields.Text()
    department = fields.Selection(DEPARTMENTS, required=True)
    workstation = fields.Selection(WORKSTATIONS, required=True)
    priority = fields.Selection(TASK_PRIORITIES, default="routine", required=True)
    state = fields.Selection(TASK_STATES, default="new", tracking=True)

    source_model = fields.Char(required=True)
    source_res_id = fields.Integer(required=True)

    sample_id = fields.Many2one("lab.sample", ondelete="set null", index=True)
    analysis_id = fields.Many2one("lab.sample.analysis", ondelete="set null", index=True)
    request_id = fields.Many2one("lab.test.request", ondelete="set null", index=True)
    interface_job_id = fields.Many2one("lab.interface.job", ondelete="set null", index=True)

    policy_id = fields.Many2one("lab.task.sla.policy", ondelete="set null")
    due_date = fields.Datetime(index=True)
    assigned_group_id = fields.Many2one("res.groups")
    assigned_user_id = fields.Many2one("res.users", tracking=True)
    assigned_at = fields.Datetime(readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)

    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=False)
    escalated = fields.Boolean(default=False)
    escalation_note = fields.Text(readonly=True)
    branch_run_id = fields.Many2one("lab.sop.branch.run", ondelete="set null")

    event_ids = fields.One2many("lab.workstation.task.event", "task_id", string="Events")

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        policy_obj = self.env["lab.task.sla.policy"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.kpi.snapshot") or "New"
            if not vals.get("policy_id"):
                policy = policy_obj._find_policy(
                    department=vals.get("department"),
                    workstation=vals.get("workstation"),
                    priority=vals.get("priority") or "routine",
                )
                if policy:
                    vals["policy_id"] = policy.id
            if not vals.get("due_date") and vals.get("policy_id"):
                policy = policy_obj.browse(vals["policy_id"])
                if policy.sla_hours:
                    vals["due_date"] = fields.Datetime.now() + timedelta(hours=policy.sla_hours)
            if not vals.get("assigned_group_id") and vals.get("policy_id"):
                policy = policy_obj.browse(vals["policy_id"])
                vals["assigned_group_id"] = policy.auto_assign_group_id.id if policy.auto_assign_group_id else False
        tasks = super().create(vals_list)
        for task in tasks:
            task._log_event("create", _("Task created"))
            if task.assigned_group_id and not task.assigned_user_id:
                task._try_auto_assign()
        return tasks

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(rec.due_date and rec.state not in ("done", "cancel") and rec.due_date < now)

    @api.model
    def _build_ref_domain(self, model_name, res_id):
        return [
            ("source_model", "=", model_name),
            ("source_res_id", "=", res_id),
            ("state", "not in", ("done", "cancel")),
        ]

    @api.model
    def get_or_create_task(self, *, model_name, res_id, title, description=False, department, workstation, priority="routine", sample=False, analysis=False, request=False, interface_job=False, branch_run=False):
        existing = self.search(self._build_ref_domain(model_name, res_id) + [("workstation", "=", workstation)], limit=1)
        if existing:
            if description and existing.description != description:
                existing.description = description
            return existing
        vals = {
            "title": title,
            "description": description or False,
            "source_model": model_name,
            "source_res_id": res_id,
            "department": department,
            "workstation": workstation,
            "priority": priority,
            "sample_id": sample.id if sample else False,
            "analysis_id": analysis.id if analysis else False,
            "request_id": request.id if request else False,
            "interface_job_id": interface_job.id if interface_job else False,
            "branch_run_id": branch_run.id if branch_run else False,
        }
        return self.create(vals)

    def _log_event(self, action, note):
        self.ensure_one()
        self.env["lab.workstation.task.event"].create(
            {
                "task_id": self.id,
                "action": action,
                "note": note,
                "event_time": fields.Datetime.now(),
                "user_id": self.env.user.id,
            }
        )

    def _try_auto_assign(self):
        self.ensure_one()
        if self.assigned_user_id or not self.assigned_group_id:
            return False
        candidate = self.assigned_group_id.user_ids.filtered(lambda u: u.active)[:1]
        if candidate:
            self.write(
                {
                    "state": "assigned" if self.state == "new" else self.state,
                    "assigned_user_id": candidate.id,
                    "assigned_at": fields.Datetime.now(),
                }
            )
            self._log_event("assign", _("Auto assigned to %s") % candidate.display_name)
            return True
        return False

    def action_assign_to_me(self):
        for rec in self:
            rec.write(
                {
                    "state": "assigned" if rec.state == "new" else rec.state,
                    "assigned_user_id": self.env.user.id,
                    "assigned_at": fields.Datetime.now(),
                }
            )
            rec._log_event("assign", _("Assigned to %s") % self.env.user.display_name)

    def action_start(self):
        for rec in self:
            if rec.state in ("done", "cancel"):
                continue
            vals = {"state": "in_progress"}
            if not rec.assigned_user_id:
                vals["assigned_user_id"] = self.env.user.id
                vals["assigned_at"] = fields.Datetime.now()
            if not rec.started_at:
                vals["started_at"] = fields.Datetime.now()
            rec.write(vals)
            rec._log_event("start", _("Task started"))

    def action_block(self):
        for rec in self:
            if rec.state in ("done", "cancel"):
                continue
            rec.state = "blocked"
            rec._log_event("block", _("Task blocked"))

    def action_unblock(self):
        for rec in self:
            if rec.state != "blocked":
                continue
            rec.state = "in_progress" if rec.started_at else "assigned"
            rec._log_event("unblock", _("Task unblocked"))

    def action_done(self):
        for rec in self:
            if rec.state in ("done", "cancel"):
                continue
            rec.write({"state": "done", "finished_at": fields.Datetime.now()})
            rec._log_event("done", _("Task done"))

    def action_cancel(self):
        for rec in self:
            if rec.state == "done":
                continue
            rec.state = "cancel"
            rec._log_event("cancel", _("Task cancelled"))

    def action_escalate(self, note=False):
        for rec in self:
            if rec.state in ("done", "cancel"):
                continue
            rec.escalated = True
            rec.escalation_note = note or _("Escalated due to SLA risk")
            rec._log_event("escalate", rec.escalation_note)
            group = rec.policy_id.escalation_group_id if rec.policy_id else False
            if group:
                todo = self.env.ref("mail.mail_activity_data_todo")
                model_id = self.env["ir.model"]._get_id("lab.workstation.task")
                for user in group.user_ids:
                    self.env["mail.activity"].create(
                        {
                            "activity_type_id": todo.id,
                            "user_id": user.id,
                            "res_model_id": model_id,
                            "res_id": rec.id,
                            "summary": _("Task escalation"),
                            "note": rec.escalation_note,
                        }
                    )

    @api.model
    def _cron_mark_overdue(self):
        now = fields.Datetime.now()
        rows = self.search(
            [
                ("state", "in", ("new", "assigned", "in_progress", "blocked")),
                ("due_date", "!=", False),
                ("due_date", "<", now),
            ]
        )
        for row in rows:
            row.state = "overdue"
            row._log_event("overdue", _("Task is overdue"))
            if not row.escalated:
                row.action_escalate(note=_("Automatically escalated by overdue cron"))

    @api.model
    def _cron_auto_assign_open(self):
        rows = self.search([("state", "=", "new")], order="priority desc, id asc", limit=500)
        for row in rows:
            row._try_auto_assign()


class LabWorkstationTaskEvent(models.Model):
    _name = "lab.workstation.task.event"
    _description = "Workstation Task Event"
    _order = "event_time desc, id desc"

    task_id = fields.Many2one("lab.workstation.task", required=True, ondelete="cascade", index=True)
    event_time = fields.Datetime(required=True, default=fields.Datetime.now)
    action = fields.Selection(
        [
            ("create", "Create"),
            ("assign", "Assign"),
            ("start", "Start"),
            ("block", "Block"),
            ("unblock", "Unblock"),
            ("done", "Done"),
            ("cancel", "Cancel"),
            ("overdue", "Overdue"),
            ("escalate", "Escalate"),
            ("branch", "Branch Rule"),
        ],
        required=True,
    )
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    note = fields.Text(required=True)


class LabTaskSlaPolicyMixin(models.Model):
    _inherit = "lab.task.sla.policy"

    @api.model
    def _find_policy(self, *, department, workstation, priority):
        if not department or not workstation:
            return False
        policy = self.search(
            [
                ("active", "=", True),
                ("department", "=", department),
                ("workstation", "=", workstation),
                "|",
                ("priority", "=", priority),
                ("priority", "=", "all"),
            ],
            order="priority desc, sequence asc, id asc",
            limit=1,
        )
        return policy


class LabSopBranchRule(models.Model):
    _name = "lab.sop.branch.rule"
    _description = "SOP Branch Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    department = fields.Selection(DEPARTMENTS, required=True)
    sample_type = fields.Selection(
        [
            ("blood", "Blood"),
            ("urine", "Urine"),
            ("stool", "Stool"),
            ("swab", "Swab"),
            ("serum", "Serum"),
            ("other", "Other"),
            ("all", "All"),
        ],
        default="all",
        required=True,
    )
    trigger_event = fields.Selection(
        [
            ("sample_received", "Sample Received"),
            ("analysis_done", "Analysis Done"),
            ("manual_review_required", "Manual Review Required"),
            ("analysis_retest", "Analysis Retest"),
            ("report_released", "Report Released"),
            ("interface_failed", "Interface Failed"),
            ("interface_dead_letter", "Interface Dead Letter"),
        ],
        required=True,
    )
    condition_json = fields.Text(
        help='Optional JSON condition map. Example: {"priority":"stat","result_flag":["high","low"]}',
    )
    action_type = fields.Selection(
        [
            ("create_task", "Create Task"),
            ("create_ncr", "Create NCR"),
            ("recollect", "Request Recollect"),
            ("interface_replay", "Create Interface Replay"),
            ("notify", "Notify Group"),
        ],
        default="create_task",
        required=True,
    )
    target_workstation = fields.Selection(WORKSTATIONS, default="review")
    task_priority = fields.Selection(TASK_PRIORITIES, default="urgent")
    owner_group_id = fields.Many2one("res.groups")
    ncr_severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="major",
    )
    notify_template = fields.Text(help="Notification body template")
    note = fields.Text()

    _branch_rule_code_uniq = models.Constraint("unique(code)", "Branch rule code must be unique.")

    def _matches_sample(self, sample):
        self.ensure_one()
        if sample.sop_id and sample.sop_id.department and sample.sop_id.department != self.department:
            return False
        if self.sample_type != "all" and sample.analysis_ids:
            st = sample.analysis_ids[:1].sample_type or "other"
            if st != self.sample_type:
                return False
        cond = self._parse_condition_json()
        if not cond:
            return True
        for key, expected in cond.items():
            if key == "priority":
                if isinstance(expected, list):
                    if sample.priority not in expected:
                        return False
                elif sample.priority != expected:
                    return False
            if key == "state":
                if isinstance(expected, list):
                    if sample.state not in expected:
                        return False
                elif sample.state != expected:
                    return False
        return True

    def _parse_condition_json(self):
        self.ensure_one()
        if not self.condition_json:
            return {}
        try:
            parsed = json.loads(self.condition_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:  # noqa: BLE001
            return {}


class LabSopBranchRun(models.Model):
    _name = "lab.sop.branch.run"
    _description = "SOP Branch Rule Run"
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    run_time = fields.Datetime(default=fields.Datetime.now, required=True)
    rule_id = fields.Many2one("lab.sop.branch.rule", required=True, ondelete="cascade", index=True)
    trigger_event = fields.Selection(related="rule_id.trigger_event", store=True)
    sample_id = fields.Many2one("lab.sample", ondelete="set null", index=True)
    analysis_id = fields.Many2one("lab.sample.analysis", ondelete="set null")
    interface_job_id = fields.Many2one("lab.interface.job", ondelete="set null")
    result_state = fields.Selection(
        [("matched", "Matched"), ("skipped", "Skipped"), ("executed", "Executed"), ("failed", "Failed")],
        default="matched",
        required=True,
    )
    output_note = fields.Text()
    task_id = fields.Many2one("lab.workstation.task", ondelete="set null")

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.custody_batch") or "New"
        return super().create(vals_list)


class LabSopBranchEngine(models.AbstractModel):
    _name = "lab.sop.branch.engine"
    _description = "SOP Branch Engine"

    @api.model
    def _eligible_rules(self, event, sample):
        return self.env["lab.sop.branch.rule"].search(
            [
                ("active", "=", True),
                ("trigger_event", "=", event),
                ("department", "=", sample.sop_id.department if sample.sop_id else "other"),
            ],
            order="sequence asc, id asc",
        )

    @api.model
    def run_rules(self, event, sample, analysis=False, interface_job=False, payload=False):
        run_obj = self.env["lab.sop.branch.run"]
        runs = run_obj.browse()
        rules = self._eligible_rules(event, sample)
        for rule in rules:
            run = run_obj.create(
                {
                    "rule_id": rule.id,
                    "sample_id": sample.id,
                    "analysis_id": analysis.id if analysis else False,
                    "interface_job_id": interface_job.id if interface_job else False,
                    "result_state": "matched",
                }
            )
            runs |= run
            if not rule._matches_sample(sample):
                run.write({"result_state": "skipped", "output_note": _("Condition not matched")})
                continue
            try:
                note, task = self._execute_rule(rule, sample, analysis=analysis, interface_job=interface_job, payload=payload, run=run)
                run.write({"result_state": "executed", "output_note": note, "task_id": task.id if task else False})
            except Exception as exc:  # noqa: BLE001
                run.write({"result_state": "failed", "output_note": str(exc)})
        return runs

    @api.model
    def _execute_rule(self, rule, sample, analysis=False, interface_job=False, payload=False, run=False):
        if rule.action_type == "create_task":
            task = self.env["lab.workstation.task"].get_or_create_task(
                model_name="lab.sample",
                res_id=sample.id,
                title=_("Branch Task: %s") % rule.name,
                description=rule.note or _("Generated by branch rule %(rule)s") % {"rule": rule.code},
                department=sample.sop_id.department if sample.sop_id else "other",
                workstation=rule.target_workstation,
                priority=rule.task_priority,
                sample=sample,
                analysis=analysis,
                interface_job=interface_job,
                branch_run=run,
            )
            task._log_event("branch", _("Created by branch rule %s") % rule.code)
            return _("Task created"), task

        if rule.action_type == "create_ncr":
            ncr = sample._auto_create_nonconformance(
                title=_("Branch NCR %s") % rule.name,
                description=rule.note or _("Generated by branch rule %(rule)s") % {"rule": rule.code},
                severity=rule.ncr_severity,
                analysis=analysis,
            )
            return _("NCR created: %s") % ncr.display_name, False

        if rule.action_type == "recollect":
            sample.write({"state": "draft"})
            sample._log_timeline("draft", _("Recollect required by branch rule %s") % rule.code)
            sample._create_signoff("retest", _("Recollect triggered by branch rule %s") % rule.code)
            return _("Sample moved to draft for recollection"), False

        if rule.action_type == "interface_replay":
            if not interface_job:
                return _("No interface job context"), False
            batch = self.env["lab.interface.replay.batch"].create(
                {
                    "name": _("Replay for %s") % interface_job.name,
                    "endpoint_id": interface_job.endpoint_id.id,
                    "reason": _("Created by branch rule %s") % rule.code,
                }
            )
            batch.action_prepare_manual([interface_job.id])
            return _("Replay batch created: %s") % batch.display_name, False

        if rule.action_type == "notify":
            group = rule.owner_group_id
            if group:
                todo = self.env.ref("mail.mail_activity_data_todo")
                model_id = self.env["ir.model"]._get_id("lab.sample")
                note = rule.notify_template or rule.note or _("Branch notify: %s") % rule.name
                for user in group.user_ids:
                    self.env["mail.activity"].create(
                        {
                            "activity_type_id": todo.id,
                            "user_id": user.id,
                            "res_model_id": model_id,
                            "res_id": sample.id,
                            "summary": _("Branch notification"),
                            "note": note,
                        }
                    )
            return _("Notification created"), False

        return _("No action executed"), False


class LabSampleBranchWorkflowMixin(models.Model):
    _inherit = "lab.sample"

    workstation_task_count = fields.Integer(compute="_compute_workstation_task_count")

    def _compute_workstation_task_count(self):
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            rec.workstation_task_count = task_obj.search_count(
                [
                    ("sample_id", "=", rec.id),
                    ("state", "not in", ("done", "cancel")),
                ]
            )

    def action_view_workstation_tasks(self):
        self.ensure_one()
        return {
            "name": _("Workstation Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": [("sample_id", "=", self.id)],
            "context": {"default_sample_id": self.id},
        }


class LabSampleAnalysisBranchWorkflowMixin(models.Model):
    _inherit = "lab.sample.analysis"

    workstation_task_count = fields.Integer(compute="_compute_workstation_task_count")

    def _compute_workstation_task_count(self):
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            rec.workstation_task_count = task_obj.search_count(
                [
                    ("analysis_id", "=", rec.id),
                    ("state", "not in", ("done", "cancel")),
                ]
            )

    def action_mark_done(self):
        result = super().action_mark_done()
        engine = self.env["lab.sop.branch.engine"]
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            if rec.needs_manual_review:
                task_obj.get_or_create_task(
                    model_name="lab.sample.analysis",
                    res_id=rec.id,
                    title=_("Manual review: %s") % rec.service_id.display_name,
                    description=rec.manual_review_reason_note or _("Manual review required"),
                    department=rec.department or "other",
                    workstation="review",
                    priority="urgent" if rec.is_critical else "routine",
                    sample=rec.sample_id,
                    analysis=rec,
                )
                engine.run_rules("manual_review_required", rec.sample_id, analysis=rec)
            else:
                open_tasks = task_obj.search(
                    [
                        ("analysis_id", "=", rec.id),
                        ("workstation", "=", "review"),
                        ("state", "not in", ("done", "cancel")),
                    ]
                )
                open_tasks.action_done()
            engine.run_rules("analysis_done", rec.sample_id, analysis=rec)
        return result

    def action_verify_result(self):
        result = super().action_verify_result()
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            open_tasks = task_obj.search(
                [
                    ("analysis_id", "=", rec.id),
                    ("state", "not in", ("done", "cancel")),
                ]
            )
            open_tasks.action_done()
        return result

    def action_request_retest(self):
        result = super().action_request_retest()
        engine = self.env["lab.sop.branch.engine"]
        for rec in self:
            engine.run_rules("analysis_retest", rec.sample_id, analysis=rec)
        return result


class LabInterfaceJobBranchWorkflowMixin(models.Model):
    _inherit = "lab.interface.job"

    workstation_task_count = fields.Integer(compute="_compute_workstation_task_count")

    def _compute_workstation_task_count(self):
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            rec.workstation_task_count = task_obj.search_count(
                [
                    ("interface_job_id", "=", rec.id),
                    ("state", "not in", ("done", "cancel")),
                ]
            )

    def action_process(self):
        result = super().action_process()
        engine = self.env["lab.sop.branch.engine"]
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            sample = rec.sample_id or (rec.request_id.sample_ids[:1] if rec.request_id else False)
            if not sample:
                continue
            if rec.state == "failed":
                task_obj.get_or_create_task(
                    model_name="lab.interface.job",
                    res_id=rec.id,
                    title=_("Interface failure: %s") % rec.name,
                    description=rec.error_message or rec.response_body or _("Interface job failed"),
                    department=sample.sop_id.department if sample.sop_id else "other",
                    workstation="interface",
                    priority="urgent",
                    sample=sample,
                    interface_job=rec,
                )
                engine.run_rules("interface_failed", sample, interface_job=rec)
            if rec.state == "dead_letter":
                task_obj.get_or_create_task(
                    model_name="lab.interface.job",
                    res_id=rec.id,
                    title=_("Interface dead-letter: %s") % rec.name,
                    description=rec.dead_letter_reason or _("Interface job dead-letter"),
                    department=sample.sop_id.department if sample.sop_id else "other",
                    workstation="interface",
                    priority="stat",
                    sample=sample,
                    interface_job=rec,
                )
                engine.run_rules("interface_dead_letter", sample, interface_job=rec)
            if rec.state == "done":
                tasks = task_obj.search(
                    [
                        ("interface_job_id", "=", rec.id),
                        ("state", "not in", ("done", "cancel")),
                    ]
                )
                tasks.action_done()
        return result


class LabInterfaceReplayBatch(models.Model):
    _name = "lab.interface.replay.batch"
    _description = "Interface Replay Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True)
    endpoint_id = fields.Many2one("lab.interface.endpoint", required=True, ondelete="cascade")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("prepared", "Prepared"),
            ("running", "Running"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )
    reason = fields.Text()
    date_from = fields.Datetime()
    date_to = fields.Datetime()
    include_failed = fields.Boolean(default=True)
    include_dead_letter = fields.Boolean(default=True)
    line_ids = fields.One2many("lab.interface.replay.batch.line", "batch_id", string="Lines")

    total_count = fields.Integer(compute="_compute_counts")
    done_count = fields.Integer(compute="_compute_counts")
    failed_count = fields.Integer(compute="_compute_counts")

    def _compute_counts(self):
        for rec in self:
            rec.total_count = len(rec.line_ids)
            rec.done_count = len(rec.line_ids.filtered(lambda x: x.state == "done"))
            rec.failed_count = len(rec.line_ids.filtered(lambda x: x.state == "failed"))

    def _job_domain(self):
        self.ensure_one()
        states = []
        if self.include_failed:
            states.append("failed")
        if self.include_dead_letter:
            states.append("dead_letter")
        if not states:
            states = ["failed", "dead_letter"]
        domain = [
            ("endpoint_id", "=", self.endpoint_id.id),
            ("state", "in", states),
        ]
        if self.date_from:
            domain.append(("processed_at", ">=", self.date_from))
        if self.date_to:
            domain.append(("processed_at", "<=", self.date_to))
        return domain

    def action_prepare(self):
        for rec in self:
            jobs = self.env["lab.interface.job"].search(rec._job_domain(), order="id asc")
            lines = []
            for job in jobs:
                lines.append((0, 0, {"job_id": job.id, "state": "queued"}))
            rec.write({"line_ids": [(5, 0, 0)] + lines, "state": "prepared"})
        return True

    def action_prepare_manual(self, job_ids):
        self.ensure_one()
        lines = []
        for job in self.env["lab.interface.job"].browse(job_ids):
            lines.append((0, 0, {"job_id": job.id, "state": "queued"}))
        self.write({"line_ids": [(5, 0, 0)] + lines, "state": "prepared"})
        return True

    def action_execute(self):
        for rec in self:
            if rec.state not in ("prepared", "draft"):
                continue
            rec.state = "running"
            for line in rec.line_ids:
                if line.state not in ("queued", "failed"):
                    continue
                line.state = "running"
                try:
                    line.job_id.action_requeue()
                    line.job_id.action_process()
                    if line.job_id.state == "done":
                        line.state = "done"
                        line.result_note = _("Replay success")
                    else:
                        line.state = "failed"
                        line.result_note = line.job_id.error_message or line.job_id.dead_letter_reason or _("Replay not successful")
                except Exception as exc:  # noqa: BLE001
                    line.state = "failed"
                    line.result_note = str(exc)
            rec.state = "done"
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})


class LabInterfaceReplayBatchLine(models.Model):
    _name = "lab.interface.replay.batch.line"
    _description = "Interface Replay Batch Line"
    _order = "id"

    batch_id = fields.Many2one("lab.interface.replay.batch", required=True, ondelete="cascade", index=True)
    job_id = fields.Many2one("lab.interface.job", required=True, ondelete="cascade", index=True)
    state = fields.Selection(
        [("queued", "Queued"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")],
        default="queued",
        required=True,
    )
    result_note = fields.Text()


class LabTaskBoardWizard(models.TransientModel):
    _name = "lab.task.board.wizard"
    _description = "Task Board"

    department = fields.Selection(DEPARTMENTS, default="chemistry", required=True)
    workstation = fields.Selection(WORKSTATIONS, default="review", required=True)

    new_count = fields.Integer(readonly=True)
    assigned_count = fields.Integer(readonly=True)
    in_progress_count = fields.Integer(readonly=True)
    blocked_count = fields.Integer(readonly=True)
    overdue_count = fields.Integer(readonly=True)
    escalated_count = fields.Integer(readonly=True)

    def _domain(self):
        self.ensure_one()
        return [
            ("department", "=", self.department),
            ("workstation", "=", self.workstation),
            ("state", "not in", ("done", "cancel")),
        ]

    def _compute_metrics(self):
        self.ensure_one()
        obj = self.env["lab.workstation.task"]
        domain = self._domain()
        return {
            "new_count": obj.search_count(domain + [("state", "=", "new")]),
            "assigned_count": obj.search_count(domain + [("state", "=", "assigned")]),
            "in_progress_count": obj.search_count(domain + [("state", "=", "in_progress")]),
            "blocked_count": obj.search_count(domain + [("state", "=", "blocked")]),
            "overdue_count": obj.search_count(domain + [("state", "=", "overdue")]),
            "escalated_count": obj.search_count(domain + [("escalated", "=", True)]),
        }

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        dep = vals.get("department") or "chemistry"
        ws = vals.get("workstation") or "review"
        rec = self.new({"department": dep, "workstation": ws})
        metrics = rec._compute_metrics()
        vals.update({k: v for k, v in metrics.items() if k in fields_list})
        return vals

    def action_refresh(self):
        for rec in self:
            rec.write(rec._compute_metrics())
        return True

    def _open_state(self, state):
        self.ensure_one()
        return {
            "name": _("Task Board"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": self._domain() + [("state", "=", state)],
        }

    def action_open_new(self):
        return self._open_state("new")

    def action_open_assigned(self):
        return self._open_state("assigned")

    def action_open_in_progress(self):
        return self._open_state("in_progress")

    def action_open_blocked(self):
        return self._open_state("blocked")

    def action_open_overdue(self):
        return self._open_state("overdue")
