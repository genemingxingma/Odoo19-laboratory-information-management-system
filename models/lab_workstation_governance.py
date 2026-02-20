from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


TASK_STATES_OPEN = ("new", "assigned", "in_progress", "blocked", "overdue")
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


class LabWorkstationRoleProfile(models.Model):
    _name = "lab.workstation.role.profile"
    _description = "Workstation Role Profile"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    user_id = fields.Many2one("res.users", ondelete="cascade", index=True)
    group_id = fields.Many2one("res.groups", ondelete="set null")

    department = fields.Selection(DEPARTMENTS, required=True)
    workstation = fields.Selection(WORKSTATIONS, required=True)

    max_open_tasks = fields.Integer(default=8, required=True)
    min_idle_minutes = fields.Integer(default=0)
    allow_overdue_pick = fields.Boolean(default=True)
    auto_claim_enabled = fields.Boolean(default=True)

    routine_weight = fields.Integer(default=10, required=True)
    urgent_weight = fields.Integer(default=30, required=True)
    stat_weight = fields.Integer(default=60, required=True)

    open_task_count = fields.Integer(compute="_compute_open_task_count")
    load_ratio = fields.Float(compute="_compute_load_ratio")
    note = fields.Text()

    _role_profile_code_uniq = models.Constraint("unique(code)", "Role profile code must be unique.")

    @api.constrains("max_open_tasks", "min_idle_minutes")
    def _check_positive_limits(self):
        for rec in self:
            if rec.max_open_tasks < 1:
                raise ValidationError(_("Maximum open tasks must be >= 1."))
            if rec.min_idle_minutes < 0:
                raise ValidationError(_("Minimum idle minutes must be >= 0."))

    @api.depends("user_id")
    def _compute_open_task_count(self):
        task_obj = self.env["lab.workstation.task"]
        for rec in self:
            if not rec.user_id:
                rec.open_task_count = 0
                continue
            rec.open_task_count = task_obj.search_count(
                [
                    ("assigned_user_id", "=", rec.user_id.id),
                    ("state", "in", TASK_STATES_OPEN),
                    ("department", "=", rec.department),
                    ("workstation", "=", rec.workstation),
                ]
            )

    @api.depends("open_task_count", "max_open_tasks")
    def _compute_load_ratio(self):
        for rec in self:
            rec.load_ratio = (float(rec.open_task_count) / float(rec.max_open_tasks)) if rec.max_open_tasks else 0.0

    def _priority_score(self, priority):
        self.ensure_one()
        if priority == "stat":
            return rec_or_default(self.stat_weight, 60)
        if priority == "urgent":
            return rec_or_default(self.urgent_weight, 30)
        return rec_or_default(self.routine_weight, 10)

    def _is_user_candidate(self, user):
        self.ensure_one()
        if not user or not user.active:
            return False
        if self.user_id and self.user_id != user:
            return False
        if self.group_id and user not in self.group_id.user_ids:
            return False
        return True

    def _can_take_task(self, task):
        self.ensure_one()
        if task.department != self.department or task.workstation != self.workstation:
            return False
        if task.state in ("done", "cancel"):
            return False
        if task.state == "overdue" and not self.allow_overdue_pick:
            return False
        if self.user_id:
            open_count = self.env["lab.workstation.task"].search_count(
                [
                    ("assigned_user_id", "=", self.user_id.id),
                    ("state", "in", TASK_STATES_OPEN),
                    ("department", "=", self.department),
                    ("workstation", "=", self.workstation),
                ]
            )
            return open_count < self.max_open_tasks
        return True


class LabWorkstationAssignmentRule(models.Model):
    _name = "lab.workstation.assignment.rule"
    _description = "Workstation Assignment Rule"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    active = fields.Boolean(default=True)

    department = fields.Selection(DEPARTMENTS, required=True)
    workstation = fields.Selection(WORKSTATIONS, required=True)
    priority = fields.Selection(TASK_PRIORITIES + [("all", "All")], default="all", required=True)

    required_group_id = fields.Many2one("res.groups")
    fallback_group_id = fields.Many2one("res.groups")

    mode = fields.Selection(
        [
            ("profile_load", "Profile Load Balance"),
            ("round_robin", "Round Robin"),
            ("first_available", "First Available"),
        ],
        default="profile_load",
        required=True,
    )
    respect_profile_limits = fields.Boolean(default=True)
    allow_overdue = fields.Boolean(default=True)
    max_candidate_scan = fields.Integer(default=100, required=True)
    last_user_id = fields.Many2one("res.users", ondelete="set null", readonly=True)
    note = fields.Text()

    _assignment_rule_code_uniq = models.Constraint("unique(code)", "Workstation assignment rule code must be unique.")

    @api.constrains("max_candidate_scan")
    def _check_max_candidate_scan(self):
        for rec in self:
            if rec.max_candidate_scan < 1:
                raise ValidationError(_("Maximum candidate scan must be >= 1."))

    @api.model
    def _find_rule(self, *, department, workstation, priority):
        if not department or not workstation:
            return False
        return self.search(
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

    def _candidate_users(self):
        self.ensure_one()
        users = self.env["res.users"].browse()
        if self.required_group_id:
            users |= self.required_group_id.user_ids
        if not users and self.fallback_group_id:
            users |= self.fallback_group_id.user_ids
        return users.filtered(lambda u: u.active)

    def _profiles_for_task(self, task):
        self.ensure_one()
        return self.env["lab.workstation.role.profile"].search(
            [
                ("active", "=", True),
                ("department", "=", task.department),
                ("workstation", "=", task.workstation),
                "|",
                ("user_id", "!=", False),
                ("group_id", "!=", False),
            ],
            order="sequence asc, id asc",
            limit=self.max_candidate_scan,
        )

    def _profile_candidates(self, task):
        self.ensure_one()
        task_obj = self.env["lab.workstation.task"]
        candidates = []
        eligible_users = self._candidate_users()
        profiles = self._profiles_for_task(task)
        seen = set()

        for profile in profiles:
            users = profile.user_id if profile.user_id else profile.group_id.user_ids
            users = users.filtered(lambda u: u in eligible_users) if eligible_users else users
            for user in users:
                if user.id in seen:
                    continue
                seen.add(user.id)
                if not profile._is_user_candidate(user):
                    continue
                if task.state == "overdue" and not (profile.allow_overdue_pick and self.allow_overdue):
                    continue
                open_count = task_obj.search_count(
                    [
                        ("assigned_user_id", "=", user.id),
                        ("state", "in", TASK_STATES_OPEN),
                        ("department", "=", task.department),
                        ("workstation", "=", task.workstation),
                    ]
                )
                if self.respect_profile_limits and open_count >= profile.max_open_tasks:
                    continue
                priority_bonus = _priority_weight(task.priority) + profile._priority_score(task.priority)
                load_penalty = int((open_count * 100) / max(profile.max_open_tasks, 1))
                candidates.append(
                    {
                        "user": user,
                        "profile": profile,
                        "group": profile.group_id,
                        "open_count": open_count,
                        "score": priority_bonus - load_penalty,
                    }
                )

        if not candidates:
            for user in eligible_users[: self.max_candidate_scan]:
                open_count = task_obj.search_count(
                    [
                        ("assigned_user_id", "=", user.id),
                        ("state", "in", TASK_STATES_OPEN),
                        ("department", "=", task.department),
                        ("workstation", "=", task.workstation),
                    ]
                )
                candidates.append(
                    {
                        "user": user,
                        "profile": False,
                        "group": self.required_group_id or self.fallback_group_id,
                        "open_count": open_count,
                        "score": _priority_weight(task.priority) - open_count,
                    }
                )

        candidates.sort(key=lambda x: (-x["score"], x["open_count"], x["user"].id))
        return candidates

    def _select_user_for_task(self, task):
        self.ensure_one()
        if not task or task.state in ("done", "cancel"):
            return False, False, False

        candidates = self._profile_candidates(task)
        if not candidates:
            return False, False, False

        if self.mode == "profile_load":
            selected = candidates[0]
            return selected["user"], selected["profile"], selected["group"]

        if self.mode == "first_available":
            selected = sorted(candidates, key=lambda x: (x["open_count"], x["user"].id))[0]
            return selected["user"], selected["profile"], selected["group"]

        if self.mode == "round_robin":
            ordered = sorted(candidates, key=lambda x: x["user"].id)
            if not self.last_user_id:
                selected = ordered[0]
            else:
                selected = ordered[0]
                for row in ordered:
                    if row["user"].id > self.last_user_id.id:
                        selected = row
                        break
            self.last_user_id = selected["user"]
            return selected["user"], selected["profile"], selected["group"]

        selected = candidates[0]
        return selected["user"], selected["profile"], selected["group"]


class LabWorkstationTaskGovernanceMixin(models.Model):
    _inherit = "lab.workstation.task"

    assignment_rule_id = fields.Many2one("lab.workstation.assignment.rule", ondelete="set null")
    role_profile_id = fields.Many2one("lab.workstation.role.profile", ondelete="set null")
    queue_score = fields.Integer(compute="_compute_queue_score")

    @api.depends("priority", "state", "due_date", "assigned_user_id")
    def _compute_queue_score(self):
        now = fields.Datetime.now()
        for rec in self:
            score = _priority_weight(rec.priority)
            if rec.state == "new":
                score += 20
            if rec.state == "overdue":
                score += 40
            if rec.state == "blocked":
                score -= 20
            if not rec.assigned_user_id:
                score += 15
            if rec.due_date:
                delta_sec = (rec.due_date - now).total_seconds()
                if delta_sec <= 0:
                    score += 25
                elif delta_sec <= 2 * 3600:
                    score += 15
                elif delta_sec <= 6 * 3600:
                    score += 8
            rec.queue_score = score

    def _try_auto_assign(self):
        self.ensure_one()
        if self.assigned_user_id or self.state in ("done", "cancel"):
            return False

        rule = self.env["lab.workstation.assignment.rule"]._find_rule(
            department=self.department,
            workstation=self.workstation,
            priority=self.priority,
        )
        if not rule:
            return super()._try_auto_assign()

        user, profile, group = rule._select_user_for_task(self)
        if not user:
            return super()._try_auto_assign()

        vals = {
            "state": "assigned" if self.state == "new" else self.state,
            "assigned_user_id": user.id,
            "assigned_at": fields.Datetime.now(),
            "assignment_rule_id": rule.id,
            "role_profile_id": profile.id if profile else False,
        }
        if not self.assigned_group_id:
            vals["assigned_group_id"] = group.id if group else (rule.required_group_id.id if rule.required_group_id else False)
        self.write(vals)
        self._log_event(
            "assign",
            _("Auto assigned by rule %(rule)s to %(user)s") % {"rule": rule.code, "user": user.display_name},
        )
        return True


class LabTaskBoardGovernanceMixin(models.TransientModel):
    _inherit = "lab.task.board.wizard"

    unassigned_count = fields.Integer(readonly=True)
    my_open_count = fields.Integer(readonly=True)
    my_overdue_count = fields.Integer(readonly=True)

    def _compute_metrics(self):
        vals = super()._compute_metrics()
        self.ensure_one()
        obj = self.env["lab.workstation.task"]
        domain = self._domain()
        vals.update(
            {
                "unassigned_count": obj.search_count(domain + [("assigned_user_id", "=", False)]),
                "my_open_count": obj.search_count(domain + [("assigned_user_id", "=", self.env.user.id)]),
                "my_overdue_count": obj.search_count(
                    domain + [("assigned_user_id", "=", self.env.user.id), ("state", "=", "overdue")]
                ),
            }
        )
        return vals

    def action_open_unassigned(self):
        self.ensure_one()
        return {
            "name": _("Unassigned Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": self._domain() + [("assigned_user_id", "=", False)],
        }

    def action_open_my_open(self):
        self.ensure_one()
        return {
            "name": _("My Open Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": self._domain() + [("assigned_user_id", "=", self.env.user.id)],
        }


class LabWorkstationMyWorkbenchWizard(models.TransientModel):
    _name = "lab.workstation.my.workbench.wizard"
    _description = "My Workbench"

    department = fields.Selection(DEPARTMENTS, default="chemistry", required=True)
    workstation = fields.Selection(WORKSTATIONS, default="review", required=True)
    include_overdue = fields.Boolean(default=True)
    candidate_limit = fields.Integer(default=30, required=True)

    candidate_count = fields.Integer(readonly=True)
    my_open_count = fields.Integer(readonly=True)
    my_overdue_count = fields.Integer(readonly=True)

    @api.constrains("candidate_limit")
    def _check_candidate_limit(self):
        for rec in self:
            if rec.candidate_limit < 1:
                raise ValidationError(_("Candidate limit must be >= 1."))

    def _candidate_domain(self):
        self.ensure_one()
        domain = [
            ("department", "=", self.department),
            ("workstation", "=", self.workstation),
            ("state", "in", TASK_STATES_OPEN),
            ("assigned_user_id", "=", False),
        ]
        if not self.include_overdue:
            domain.append(("state", "!=", "overdue"))
        return domain

    def action_refresh(self):
        obj = self.env["lab.workstation.task"]
        for rec in self:
            rec.candidate_count = obj.search_count(rec._candidate_domain())
            rec.my_open_count = obj.search_count(
                [
                    ("department", "=", rec.department),
                    ("workstation", "=", rec.workstation),
                    ("state", "in", TASK_STATES_OPEN),
                    ("assigned_user_id", "=", self.env.user.id),
                ]
            )
            rec.my_overdue_count = obj.search_count(
                [
                    ("department", "=", rec.department),
                    ("workstation", "=", rec.workstation),
                    ("state", "=", "overdue"),
                    ("assigned_user_id", "=", self.env.user.id),
                ]
            )
        return True

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        dep = vals.get("department") or "chemistry"
        ws = vals.get("workstation") or "review"
        rec = self.new(
            {
                "department": dep,
                "workstation": ws,
                "include_overdue": vals.get("include_overdue", True),
                "candidate_limit": vals.get("candidate_limit", 30),
            }
        )
        rec.action_refresh()
        vals.update(
            {
                "candidate_count": rec.candidate_count,
                "my_open_count": rec.my_open_count,
                "my_overdue_count": rec.my_overdue_count,
            }
        )
        return vals

    def action_open_candidates(self):
        self.ensure_one()
        return {
            "name": _("Candidate Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": self._candidate_domain(),
            "context": {
                "search_default_f_open": 1,
            },
        }

    def action_auto_claim_top(self):
        self.ensure_one()
        task_obj = self.env["lab.workstation.task"]
        rows = task_obj.search(self._candidate_domain(), order="queue_score desc, priority desc, id asc", limit=self.candidate_limit)
        claimed = 0
        for row in rows:
            if row.assigned_user_id:
                continue
            row.write(
                {
                    "assigned_user_id": self.env.user.id,
                    "assigned_at": fields.Datetime.now(),
                    "state": "assigned" if row.state == "new" else row.state,
                }
            )
            row._log_event("assign", _("Auto-claimed from My Workbench by %s") % self.env.user.display_name)
            claimed += 1
        self.action_refresh()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("My Workbench"),
                "message": _("Claimed %(count)s tasks.") % {"count": claimed},
                "sticky": False,
                "type": "success",
            },
        }


def _priority_weight(priority):
    if priority == "stat":
        return 100
    if priority == "urgent":
        return 60
    return 25


def rec_or_default(value, default):
    return value if isinstance(value, int) else default
