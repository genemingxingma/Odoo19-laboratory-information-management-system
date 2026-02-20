from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabCustodySLAPolicy(models.Model):
    _name = "lab.custody.sla.policy"
    _description = "Lab Custody SLA Policy"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(default=False)
    note = fields.Text()
    line_ids = fields.One2many("lab.custody.sla.policy.line", "policy_id", string="Policy Lines", copy=True)

    @api.constrains("is_default")
    def _check_single_default(self):
        for rec in self.filtered("is_default"):
            others = self.search_count([("id", "!=", rec.id), ("is_default", "=", True)])
            if others:
                raise UserError(_("Only one SLA policy can be default."))


class LabCustodySLAPolicyLine(models.Model):
    _name = "lab.custody.sla.policy.line"
    _description = "Lab Custody SLA Policy Line"
    _order = "severity, id"

    policy_id = fields.Many2one("lab.custody.sla.policy", required=True, ondelete="cascade")
    severity = fields.Selection(
        [
            ("minor", "Minor"),
            ("major", "Major"),
            ("critical", "Critical"),
        ],
        required=True,
        default="major",
    )
    target_hours = fields.Integer(required=True, default=48)
    warning_hours = fields.Integer(required=True, default=8)
    require_qa_signoff = fields.Boolean(default=True)
    require_effectiveness = fields.Boolean(default=True)
    auto_escalate = fields.Boolean(default=True)
    escalation_hours_l1 = fields.Integer(default=4)
    escalation_hours_l2 = fields.Integer(default=12)
    escalation_hours_l3 = fields.Integer(default=24)


class LabCustodyInvestigation(models.Model):
    _inherit = "lab.custody.investigation"

    sla_policy_id = fields.Many2one("lab.custody.sla.policy", string="SLA Policy", tracking=True)
    sla_target_hours = fields.Integer(default=48)
    sla_warning_hours = fields.Integer(default=8)
    sla_deadline = fields.Datetime(compute="_compute_sla_deadline", store=True)
    sla_remaining_hours = fields.Float(compute="_compute_sla_metrics", store=True, compute_sudo=True)
    sla_state = fields.Selection(
        [
            ("na", "N/A"),
            ("on_track", "On Track"),
            ("warning", "Warning"),
            ("breach", "Breached"),
            ("closed", "Closed"),
        ],
        compute="_compute_sla_metrics",
        store=True,
        compute_sudo=True,
    )
    escalation_level = fields.Selection(
        [
            ("none", "None"),
            ("l1", "L1"),
            ("l2", "L2"),
            ("l3", "L3"),
        ],
        default="none",
        tracking=True,
    )
    sla_breach_notified = fields.Boolean(default=False)
    require_qa_signoff = fields.Boolean(default=True)
    require_effectiveness = fields.Boolean(default=True)
    qa_signed_by_id = fields.Many2one("res.users", readonly=True)
    qa_signed_at = fields.Datetime(readonly=True)
    escalation_log_ids = fields.One2many("lab.custody.escalation.log", "investigation_id", string="Escalation Logs")
    escalation_log_count = fields.Integer(compute="_compute_escalation_log_count")

    @api.depends("escalation_log_ids")
    def _compute_escalation_log_count(self):
        grouped = self.env["lab.custody.escalation.log"].read_group(
            [("investigation_id", "in", self.ids)], ["investigation_id"], ["investigation_id"]
        )
        count_map = {
            item["investigation_id"][0]: item["investigation_id_count"]
            for item in grouped
            if item.get("investigation_id")
        }
        for rec in self:
            rec.escalation_log_count = count_map.get(rec.id, 0)

    @api.depends("detected_date", "sla_target_hours")
    def _compute_sla_deadline(self):
        for rec in self:
            rec.sla_deadline = fields.Datetime.add(rec.detected_date, hours=rec.sla_target_hours) if rec.detected_date else False

    @api.depends("sla_deadline", "state", "sla_warning_hours")
    def _compute_sla_metrics(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("closed", "cancel"):
                rec.sla_remaining_hours = 0
                rec.sla_state = "closed"
                continue
            if not rec.sla_deadline:
                rec.sla_remaining_hours = 0
                rec.sla_state = "na"
                continue
            diff = rec.sla_deadline - now
            remaining_hours = diff.total_seconds() / 3600.0
            rec.sla_remaining_hours = remaining_hours
            if remaining_hours < 0:
                rec.sla_state = "breach"
            elif remaining_hours <= rec.sla_warning_hours:
                rec.sla_state = "warning"
            else:
                rec.sla_state = "on_track"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._apply_sla_policy()
        return records

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("skip_sla_apply"):
            return result
        if any(k in vals for k in ("severity", "sla_policy_id")):
            for rec in self:
                rec._apply_sla_policy()
        return result

    def _get_default_policy(self):
        policy = self.env["lab.custody.sla.policy"].search([("is_default", "=", True), ("active", "=", True)], limit=1)
        if not policy:
            policy = self.env["lab.custody.sla.policy"].search([("active", "=", True)], limit=1)
        return policy

    def _apply_sla_policy(self):
        for rec in self:
            policy = rec.sla_policy_id or rec._get_default_policy()
            if not policy:
                continue
            line = policy.line_ids.filtered(lambda x: x.severity == rec.severity)[:1]
            if not line:
                line = policy.line_ids[:1]
            vals = {"sla_policy_id": policy.id}
            if line:
                vals.update(
                    {
                        "sla_target_hours": line.target_hours,
                        "sla_warning_hours": line.warning_hours,
                        "require_qa_signoff": line.require_qa_signoff,
                        "require_effectiveness": line.require_effectiveness,
                    }
                )
            super(LabCustodyInvestigation, rec.with_context(skip_sla_apply=True)).write(vals)

    def action_recompute_sla(self):
        for rec in self:
            rec._apply_sla_policy()

    def action_qa_signoff(self):
        for rec in self:
            rec.write(
                {
                    "qa_signed_by_id": self.env.user.id,
                    "qa_signed_at": fields.Datetime.now(),
                }
            )
            rec.message_post(body=_("QA sign-off completed by %s") % self.env.user.name)

    def action_view_escalation_logs(self):
        self.ensure_one()
        return {
            "name": _("Escalation Logs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.escalation.log",
            "view_mode": "list,form",
            "domain": [("investigation_id", "=", self.id)],
            "context": {"default_investigation_id": self.id},
        }

    def action_close(self):
        for rec in self:
            if rec.require_qa_signoff and not rec.qa_signed_by_id:
                raise UserError(_("QA sign-off is required before closing."))
            if rec.require_effectiveness and not rec.effectiveness_conclusion:
                raise UserError(_("Effectiveness conclusion is required before closing."))
        return super().action_close()

    def _notify_breach(self):
        self.ensure_one()
        summary = _("Custody SLA breach")
        message = _(
            "Investigation %(name)s breached SLA. Severity=%(severity)s, deadline=%(deadline)s"
        ) % {
            "name": self.name,
            "severity": self.severity,
            "deadline": self.sla_deadline,
        }
        users = (self.owner_id | self.qa_reviewer_id)
        manager_group = self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
        if manager_group:
            users |= manager_group.user_ids
        if not users:
            users = self.env.user
        entries = []
        for user in users:
            entries.append({"res_id": self.id, "user_id": user.id, "summary": summary, "note": message})
        self.env["lab.activity.helper.mixin"].create_unique_todo_activities(
            model_name="lab.custody.investigation",
            entries=entries,
        )

    def _make_escalation(self, level, message):
        self.ensure_one()
        level_order = {"none": 0, "l1": 1, "l2": 2, "l3": 3}
        if level_order[level] <= level_order[self.escalation_level]:
            return
        self.write({"escalation_level": level})
        self.env["lab.custody.escalation.log"].create(
            {
                "investigation_id": self.id,
                "level": level,
                "triggered_at": fields.Datetime.now(),
                "triggered_by_id": self.env.user.id,
                "message": message,
            }
        )
        self.message_post(body=message)

    def action_escalate_manual(self):
        for rec in self:
            next_level = "l1"
            if rec.escalation_level == "l1":
                next_level = "l2"
            elif rec.escalation_level == "l2":
                next_level = "l3"
            rec._make_escalation(next_level, _("Manual escalation to %s") % next_level.upper())

    @api.model
    def _cron_escalate_sla(self):
        open_recs = self.search([("state", "not in", ("closed", "cancel")), ("sla_deadline", "!=", False)])
        now = fields.Datetime.now()
        policies = self.env["lab.custody.sla.policy"]
        for rec in open_recs:
            policy = rec.sla_policy_id or rec._get_default_policy()
            line = policy.line_ids.filtered(lambda x: x.severity == rec.severity)[:1] if policy else False
            if rec.sla_state == "breach" and not rec.sla_breach_notified:
                rec._notify_breach()
                rec.sla_breach_notified = True
            if not line or not line.auto_escalate:
                continue
            breach_hours = max(0.0, (now - rec.sla_deadline).total_seconds() / 3600.0)
            if breach_hours >= line.escalation_hours_l3:
                rec._make_escalation("l3", _("Auto escalation to L3 (breach %.1f h)") % breach_hours)
            elif breach_hours >= line.escalation_hours_l2:
                rec._make_escalation("l2", _("Auto escalation to L2 (breach %.1f h)") % breach_hours)
            elif breach_hours >= line.escalation_hours_l1:
                rec._make_escalation("l1", _("Auto escalation to L1 (breach %.1f h)") % breach_hours)


class LabCustodyEscalationLog(models.Model):
    _name = "lab.custody.escalation.log"
    _description = "Lab Custody Escalation Log"
    _order = "triggered_at desc, id desc"

    investigation_id = fields.Many2one("lab.custody.investigation", required=True, ondelete="cascade")
    level = fields.Selection(
        [
            ("l1", "L1"),
            ("l2", "L2"),
            ("l3", "L3"),
        ],
        required=True,
    )
    triggered_at = fields.Datetime(required=True)
    triggered_by_id = fields.Many2one("res.users", required=True)
    message = fields.Text(required=True)
