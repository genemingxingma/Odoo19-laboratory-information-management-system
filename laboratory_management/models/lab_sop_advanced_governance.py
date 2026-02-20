import json
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabDepartmentSopVersion(models.Model):
    _name = "lab.department.sop.version"
    _description = "Department SOP Version Snapshot"
    _order = "sop_id, version_no desc, id desc"

    name = fields.Char(required=True)
    sop_id = fields.Many2one("lab.department.sop", required=True, ondelete="cascade", index=True)
    version_no = fields.Integer(required=True, default=1)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("active", "Active"), ("retired", "Retired")],
        default="draft",
        required=True,
    )
    is_active_version = fields.Boolean(compute="_compute_is_active_version")
    step_json = fields.Text(readonly=True)
    exception_route_json = fields.Text(readonly=True)
    source_note = fields.Text()

    _sop_version_uniq = models.Constraint(
        "unique(sop_id, version_no)",
        "SOP version number must be unique within one SOP.",
    )

    @api.depends("state")
    def _compute_is_active_version(self):
        for rec in self:
            rec.is_active_version = rec.state == "active"

    @api.model
    def _next_version_no(self, sop):
        latest = self.search([("sop_id", "=", sop.id)], order="version_no desc, id desc", limit=1)
        return (latest.version_no if latest else 0) + 1

    @api.model
    def _build_snapshot_payload(self, sop):
        steps = []
        for step in sop.step_ids.sorted("sequence"):
            steps.append(
                {
                    "sequence": step.sequence,
                    "step_code": step.step_code,
                    "name": step.name,
                    "workstation_role": step.workstation_role,
                    "required": step.required,
                    "max_hours_from_prev": step.max_hours_from_prev,
                    "on_fail_action": step.on_fail_action,
                    "control_note": step.control_note or "",
                }
            )

        routes = []
        for route in sop.exception_route_ids.sorted("sequence"):
            routes.append(
                {
                    "sequence": route.sequence,
                    "trigger_event": route.trigger_event,
                    "severity": route.severity,
                    "route_action": route.route_action,
                    "owner_group_id": route.owner_group_id.id if route.owner_group_id else False,
                    "sla_hours": route.sla_hours,
                    "note": route.note or "",
                }
            )

        return {"steps": steps, "routes": routes}

    @api.model
    def create_from_sop(self, sop, note=False):
        payload = self._build_snapshot_payload(sop)
        ver_no = self._next_version_no(sop)
        return self.create(
            {
                "name": "%s v%s" % (sop.code, ver_no),
                "sop_id": sop.id,
                "version_no": ver_no,
                "state": "draft",
                "step_json": json.dumps(payload["steps"], ensure_ascii=False),
                "exception_route_json": json.dumps(payload["routes"], ensure_ascii=False),
                "source_note": note or _("Created from SOP form snapshot."),
            }
        )

    def action_approve(self):
        self.write({"state": "approved"})
        return True

    def _payload(self):
        self.ensure_one()
        try:
            steps = json.loads(self.step_json or "[]")
        except Exception:  # noqa: BLE001
            steps = []
        try:
            routes = json.loads(self.exception_route_json or "[]")
        except Exception:  # noqa: BLE001
            routes = []
        return steps, routes

    def action_apply_to_sop(self):
        for rec in self:
            steps, routes = rec._payload()
            if not steps:
                raise UserError(_("Snapshot has no SOP steps and cannot be applied."))

            step_lines = []
            for row in steps:
                step_lines.append(
                    (
                        0,
                        0,
                        {
                            "sequence": row.get("sequence", 10),
                            "step_code": row.get("step_code") or "step",
                            "name": row.get("name") or "Step",
                            "workstation_role": row.get("workstation_role") or "analyst",
                            "required": bool(row.get("required", True)),
                            "max_hours_from_prev": int(row.get("max_hours_from_prev", 0) or 0),
                            "on_fail_action": row.get("on_fail_action") or "manual_review",
                            "control_note": row.get("control_note") or False,
                        },
                    )
                )

            route_lines = []
            for row in routes:
                route_lines.append(
                    (
                        0,
                        0,
                        {
                            "sequence": row.get("sequence", 10),
                            "trigger_event": row.get("trigger_event") or "specimen_issue",
                            "severity": row.get("severity") or "major",
                            "route_action": row.get("route_action") or "manual_review",
                            "owner_group_id": row.get("owner_group_id") or False,
                            "sla_hours": int(row.get("sla_hours", 0) or 0),
                            "note": row.get("note") or False,
                        },
                    )
                )

            rec.sop_id.write(
                {
                    "step_ids": [(5, 0, 0)] + step_lines,
                    "exception_route_ids": [(5, 0, 0)] + route_lines,
                }
            )
        return True

    def action_activate_version(self):
        for rec in self:
            siblings = self.search([("sop_id", "=", rec.sop_id.id), ("id", "!=", rec.id), ("state", "=", "active")])
            siblings.write({"state": "retired"})
            rec.state = "active"
            rec.action_apply_to_sop()
        return True


class LabDepartmentSopVersionMixin(models.Model):
    _inherit = "lab.department.sop"

    version_count = fields.Integer(compute="_compute_version_count")

    def _compute_version_count(self):
        obj = self.env["lab.department.sop.version"]
        for rec in self:
            rec.version_count = obj.search_count([("sop_id", "=", rec.id)])

    def action_create_version_snapshot(self):
        self.ensure_one()
        version = self.env["lab.department.sop.version"].create_from_sop(self)
        return {
            "name": _("SOP Version"),
            "type": "ir.actions.act_window",
            "res_model": "lab.department.sop.version",
            "res_id": version.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_versions(self):
        self.ensure_one()
        return {
            "name": _("SOP Versions"),
            "type": "ir.actions.act_window",
            "res_model": "lab.department.sop.version",
            "view_mode": "list,form",
            "domain": [("sop_id", "=", self.id)],
            "context": {"default_sop_id": self.id},
        }


class LabSopExceptionDecisionSlaMixin(models.Model):
    _inherit = "lab.sop.exception.decision"

    sla_hours = fields.Integer(default=0, help="0 means no SLA escalation for this decision.")


class LabSopExecutionExceptionSlaMixin(models.Model):
    _inherit = "lab.sop.execution"

    exception_trigger = fields.Selection(
        [
            ("critical", "Critical Result"),
            ("delta_fail", "Delta Check Failed"),
            ("qc_reject", "QC Reject"),
            ("instrument_error", "Instrument Error"),
            ("specimen_issue", "Specimen Rejection"),
            ("retest_exceeded", "Retest Limit Exceeded"),
            ("manual_review_reject", "Manual Review Rejected"),
            ("other", "Other"),
        ],
        readonly=True,
        copy=False,
    )
    exception_opened_at = fields.Datetime(readonly=True, copy=False)
    exception_deadline = fields.Datetime(readonly=True, copy=False)
    exception_sla_hours = fields.Integer(readonly=True, copy=False)
    exception_escalated = fields.Boolean(default=False, readonly=True, copy=False)
    exception_escalated_at = fields.Datetime(readonly=True, copy=False)

    def _mark_exception_window(self, trigger, reason=False):
        self.ensure_one()
        decision = self.env["lab.sop.exception.decision"]._select_for_execution(self, trigger=trigger, severity=self._current_severity())
        sla_hours = decision.sla_hours if decision and decision.sla_hours else 0
        vals = {
            "exception_trigger": trigger,
            "exception_opened_at": fields.Datetime.now(),
            "exception_sla_hours": sla_hours,
            "exception_deadline": fields.Datetime.now() + timedelta(hours=sla_hours) if sla_hours else False,
            "exception_escalated": False,
            "exception_escalated_at": False,
        }
        self.write(vals)
        self._log_event(
            "step_failed",
            reason or _("Exception window opened. Trigger: %s") % trigger,
        )

    def action_fail_current_step(self, reason=False, trigger=False):
        result = super().action_fail_current_step(reason=reason, trigger=trigger)
        for rec in self:
            if rec.state == "exception":
                rec._mark_exception_window(trigger or "other", reason=reason)
        return result


class LabSopExceptionSlaMonitor(models.AbstractModel):
    _name = "lab.sop.exception.sla.monitor"
    _description = "SOP Exception SLA Monitor"

    @api.model
    def _cron_escalate_overdue_sop_exceptions(self):
        now = fields.Datetime.now()
        executions = self.env["lab.sop.execution"].search(
            [
                ("state", "=", "exception"),
                ("exception_deadline", "!=", False),
                ("exception_deadline", "<", now),
                ("exception_escalated", "=", False),
            ],
            limit=300,
        )
        for execution in executions:
            execution._route_escalate(
                reason=_("Exception SLA exceeded at %s") % fields.Datetime.to_string(now),
                route_group=False,
            )
            execution.write({"exception_escalated": True, "exception_escalated_at": now})


class LabRetestAnalyticsReport(models.Model):
    _name = "lab.retest.analytics.report"
    _description = "Retest Analytics Report"
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
            ("all", "All"),
        ],
        default="all",
        required=True,
    )
    line_ids = fields.One2many("lab.retest.analytics.report.line", "report_id", string="Lines")

    total_retests = fields.Integer(readonly=True)
    sample_count = fields.Integer(readonly=True)
    escalated_sample_count = fields.Integer(readonly=True)
    recollect_event_count = fields.Integer(readonly=True)
    avg_retests_per_sample = fields.Float(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def _base_domain(self):
        self.ensure_one()
        dt_from = datetime.combine(self.start_date, time.min)
        dt_to = datetime.combine(self.end_date, time.max)
        domain = [
            ("retest_of_id", "!=", False),
            ("create_date", ">=", fields.Datetime.to_string(dt_from)),
            ("create_date", "<=", fields.Datetime.to_string(dt_to)),
        ]
        if self.department != "all":
            domain.append(("department", "=", self.department))
        return domain

    def action_generate(self):
        for rec in self:
            analysis_obj = self.env["lab.sample.analysis"]
            rows = analysis_obj.search(rec._base_domain())

            grouped = defaultdict(lambda: {"sample_ids": set(), "count": 0, "critical": 0, "delta_sum": 0.0, "delta_cnt": 0, "last": False})
            for line in rows:
                key = line.service_id.id
                grp = grouped[key]
                grp["count"] += 1
                grp["sample_ids"].add(line.sample_id.id)
                if line.is_critical:
                    grp["critical"] += 1
                if line.delta_check_value not in (False, None):
                    grp["delta_sum"] += abs(line.delta_check_value)
                    grp["delta_cnt"] += 1
                if not grp["last"] or (line.create_date and line.create_date > grp["last"]):
                    grp["last"] = line.create_date

            line_vals = []
            for service_id, data in grouped.items():
                line_vals.append(
                    (
                        0,
                        0,
                        {
                            "service_id": service_id,
                            "retest_count": data["count"],
                            "sample_count": len(data["sample_ids"]),
                            "critical_retest_count": data["critical"],
                            "avg_delta_abs": (data["delta_sum"] / data["delta_cnt"]) if data["delta_cnt"] else 0.0,
                            "last_retest_at": data["last"],
                        },
                    )
                )

            sample_ids = list({x.sample_id.id for x in rows if x.sample_id})
            events = self.env["lab.sop.execution.event"].search(
                [
                    ("sample_id", "in", sample_ids),
                    ("event_time", ">=", fields.Datetime.to_string(datetime.combine(rec.start_date, time.min))),
                    ("event_time", "<=", fields.Datetime.to_string(datetime.combine(rec.end_date, time.max))),
                    ("event_type", "in", ("route_escalate", "route_recollect")),
                ]
            )

            escalated_samples = {ev.sample_id.id for ev in events if ev.event_type == "route_escalate" and ev.sample_id}
            recollect_count = len(events.filtered(lambda x: x.event_type == "route_recollect"))
            rec.write(
                {
                    "line_ids": [(5, 0, 0)] + line_vals,
                    "total_retests": len(rows),
                    "sample_count": len(sample_ids),
                    "escalated_sample_count": len(escalated_samples),
                    "recollect_event_count": recollect_count,
                    "avg_retests_per_sample": (len(rows) / len(sample_ids)) if sample_ids else 0.0,
                }
            )
        return True


class LabRetestAnalyticsReportLine(models.Model):
    _name = "lab.retest.analytics.report.line"
    _description = "Retest Analytics Report Line"
    _order = "retest_count desc, id"

    report_id = fields.Many2one("lab.retest.analytics.report", required=True, ondelete="cascade", index=True)
    service_id = fields.Many2one("lab.service", required=True, ondelete="cascade")
    retest_count = fields.Integer(readonly=True)
    sample_count = fields.Integer(readonly=True)
    critical_retest_count = fields.Integer(readonly=True)
    avg_delta_abs = fields.Float(readonly=True)
    last_retest_at = fields.Datetime(readonly=True)
