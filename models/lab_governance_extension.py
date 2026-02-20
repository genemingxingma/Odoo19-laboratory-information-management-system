from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


DEPARTMENTS = [
    ("chemistry", "Clinical Chemistry"),
    ("hematology", "Hematology"),
    ("microbiology", "Microbiology"),
    ("immunology", "Immunology"),
    ("other", "Other"),
]

WORKSTATIONS = [
    ("accession", "Accession"),
    ("analysis", "Analysis"),
    ("review", "Review"),
    ("quality", "Quality"),
    ("integration", "Integration"),
    ("billing", "Billing"),
    ("portal", "Portal"),
]

TASK_WORKSTATIONS = [
    ("accession", "Accession"),
    ("analysis", "Analysis"),
    ("review", "Review"),
    ("quality", "Quality"),
    ("interface", "Interface"),
    ("billing", "Billing"),
]


class LabDepartmentExceptionTemplate(models.Model):
    _name = "lab.department.exception.template"
    _description = "Department Exception Template"
    _order = "department, sequence, id"

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
            ("manual_review_required", "Manual Review Required"),
            ("critical_result", "Critical Result"),
            ("delta_fail", "Delta Fail"),
            ("qc_reject", "QC Reject"),
            ("interface_failed", "Interface Failed"),
            ("interface_dead_letter", "Interface Dead Letter"),
            ("retest_exceeded", "Retest Exceeded"),
        ],
        required=True,
    )
    severity = fields.Selection(
        [("minor", "Minor"), ("major", "Major"), ("critical", "Critical")],
        default="major",
        required=True,
    )
    route_action = fields.Selection(
        [
            ("task", "Create Task"),
            ("ncr", "Create NCR"),
            ("task_ncr", "Create Task + NCR"),
            ("notify", "Notify"),
        ],
        default="task",
        required=True,
    )
    task_workstation = fields.Selection(TASK_WORKSTATIONS, default="review")
    task_priority = fields.Selection(
        [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        default="urgent",
    )
    owner_group_id = fields.Many2one("res.groups")
    sla_hours = fields.Integer(default=0)
    title_template = fields.Char(
        default="[{code}] {sample} {event}",
        help="Use placeholders: {code} {sample} {event} {analysis} {department}",
    )
    note_template = fields.Text(
        default="Template {name} triggered on sample {sample} event {event}.",
    )

    _code_uniq = models.Constraint("unique(code)", "Exception template code must be unique.")

    @api.constrains("sla_hours")
    def _check_sla(self):
        for rec in self:
            if rec.sla_hours < 0:
                raise ValidationError(_("SLA hours must be >= 0."))

    def _render(self, text, payload):
        self.ensure_one()
        return (text or "").format_map(payload)

    def _matches_context(self, sample, event):
        self.ensure_one()
        if self.trigger_event != event:
            return False
        sample_type = sample.analysis_ids[:1].sample_type if sample.analysis_ids else "other"
        if self.sample_type != "all" and sample_type != self.sample_type:
            return False
        department = sample.sop_id.department if sample.sop_id else "other"
        if department != self.department:
            return False
        return True

    def apply_exception(self, *, sample, event, analysis=False, interface_job=False):
        self.ensure_one()
        if not self._matches_context(sample, event):
            return False

        payload = {
            "code": self.code,
            "name": self.name,
            "sample": sample.name,
            "event": event,
            "analysis": analysis.service_id.display_name if analysis else "",
            "department": self.department,
        }
        title = self._render(self.title_template, payload)
        note = self._render(self.note_template, payload)

        task = False
        if self.route_action in ("task", "task_ncr"):
            task = self.env["lab.workstation.task"].get_or_create_task(
                model_name="lab.sample",
                res_id=sample.id,
                title=title,
                description=note,
                department=self.department,
                workstation=self.task_workstation,
                priority=self.task_priority,
                sample=sample,
                analysis=analysis,
                interface_job=interface_job,
            )
            if self.sla_hours and not task.due_date:
                task.due_date = fields.Datetime.now() + timedelta(hours=self.sla_hours)
            if self.owner_group_id and not task.assigned_group_id:
                task.assigned_group_id = self.owner_group_id.id
            task._log_event("branch", _("Created by exception template %s") % self.code)

        if self.route_action in ("ncr", "task_ncr"):
            sample._auto_create_nonconformance(
                title=title,
                description=note,
                severity=self.severity,
                analysis=analysis,
            )

        if self.owner_group_id and self.route_action == "notify":
            todo = self.env.ref("mail.mail_activity_data_todo")
            model_id = self.env["ir.model"]._get_id("lab.sample")
            for user in self.owner_group_id.user_ids:
                self.env["mail.activity"].create(
                    {
                        "activity_type_id": todo.id,
                        "user_id": user.id,
                        "res_model_id": model_id,
                        "res_id": sample.id,
                        "summary": _("Exception notification"),
                        "note": note,
                    }
                )
        return task


class LabSopBranchEngineTemplateMixin(models.AbstractModel):
    _inherit = "lab.sop.branch.engine"

    @api.model
    def run_rules(self, event, sample, analysis=False, interface_job=False, payload=False):
        runs = super().run_rules(event, sample, analysis=analysis, interface_job=interface_job, payload=payload)
        executed = runs.filtered(lambda x: x.result_state == "executed")
        if executed:
            return runs

        template_obj = self.env["lab.department.exception.template"]
        templates = template_obj.search(
            [
                ("active", "=", True),
                ("department", "=", sample.sop_id.department if sample.sop_id else "other"),
                ("trigger_event", "=", event),
            ],
            order="sequence asc, id asc",
            limit=1,
        )
        for tmpl in templates:
            task = tmpl.apply_exception(sample=sample, event=event, analysis=analysis, interface_job=interface_job)
            if task:
                task._log_event("branch", _("Executed by exception template %s") % tmpl.code)
        return runs


class LabPermissionAuditSnapshot(models.Model):
    _name = "lab.permission.audit.snapshot"
    _description = "Permission Audit Snapshot"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "audit_time desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    audit_time = fields.Datetime(default=fields.Datetime.now, required=True)
    generated_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)

    include_custom_groups = fields.Boolean(default=False)
    additional_group_ids = fields.Many2many("res.groups", string="Additional Groups")

    total_checks = fields.Integer(readonly=True)
    ok_count = fields.Integer(readonly=True)
    warning_count = fields.Integer(readonly=True)
    missing_count = fields.Integer(readonly=True)

    line_ids = fields.One2many("lab.permission.audit.snapshot.line", "snapshot_id", string="Lines")
    summary = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def _default_groups(self):
        xmlids = [
            "laboratory_management.group_lab_reception",
            "laboratory_management.group_lab_analyst",
            "laboratory_management.group_lab_reviewer",
            "laboratory_management.group_lab_manager",
            "laboratory_management.group_lab_quality_manager",
            "laboratory_management.group_lab_interface_admin",
        ]
        groups = self.env["res.groups"].browse()
        for x in xmlids:
            grp = self.env.ref(x, raise_if_not_found=False)
            if grp:
                groups |= grp
        return groups

    def _required_workstations(self):
        return [x[0] for x in WORKSTATIONS]

    def action_generate(self):
        matrix_obj = self.env["lab.permission.matrix"]
        for rec in self:
            groups = rec._default_groups()
            if rec.include_custom_groups and rec.additional_group_ids:
                groups |= rec.additional_group_ids

            lines = []
            ok_count = 0
            warning_count = 0
            missing_count = 0

            for group in groups:
                for workstation in rec._required_workstations():
                    row = matrix_obj.search(
                        [
                            ("group_id", "=", group.id),
                            ("workstation", "=", workstation),
                        ],
                        limit=1,
                    )
                    if not row:
                        status = "missing"
                        issue = _("No permission matrix row")
                        expected = _("At least can_view")
                        actual = _("none")
                        missing_count += 1
                    else:
                        if not row.can_view:
                            status = "warning"
                            issue = _("can_view disabled")
                            expected = _("can_view = True")
                            actual = _("can_view = False")
                            warning_count += 1
                        else:
                            status = "ok"
                            issue = _("OK")
                            expected = _("Defined")
                            actual = _("Defined")
                            ok_count += 1

                    lines.append(
                        (
                            0,
                            0,
                            {
                                "group_id": group.id,
                                "workstation": workstation,
                                "status": status,
                                "issue": issue,
                                "expected": expected,
                                "actual": actual,
                            },
                        )
                    )

            total = len(lines)
            rec.write(
                {
                    "line_ids": [(5, 0, 0)] + lines,
                    "total_checks": total,
                    "ok_count": ok_count,
                    "warning_count": warning_count,
                    "missing_count": missing_count,
                    "summary": _(
                        "Audit complete: total=%(t)s, ok=%(o)s, warning=%(w)s, missing=%(m)s"
                    )
                    % {"t": total, "o": ok_count, "w": warning_count, "m": missing_count},
                }
            )
        return True

    def action_open_missing(self):
        self.ensure_one()
        return {
            "name": _("Missing Permission Rows"),
            "type": "ir.actions.act_window",
            "res_model": "lab.permission.audit.snapshot.line",
            "view_mode": "list",
            "domain": [
                ("snapshot_id", "=", self.id),
                ("status", "in", ("missing", "warning")),
            ],
        }


class LabPermissionAuditSnapshotLine(models.Model):
    _name = "lab.permission.audit.snapshot.line"
    _description = "Permission Audit Snapshot Line"
    _order = "snapshot_id, group_id, workstation"

    snapshot_id = fields.Many2one("lab.permission.audit.snapshot", required=True, ondelete="cascade", index=True)
    group_id = fields.Many2one("res.groups", required=True)
    workstation = fields.Selection(WORKSTATIONS, required=True)
    status = fields.Selection(
        [("ok", "OK"), ("warning", "Warning"), ("missing", "Missing")],
        required=True,
    )
    issue = fields.Char(required=True)
    expected = fields.Char(required=True)
    actual = fields.Char(required=True)


class LabPermissionAuditWizard(models.TransientModel):
    _name = "lab.permission.audit.wizard"
    _description = "Permission Audit Wizard"

    include_custom_groups = fields.Boolean(default=False)
    additional_group_ids = fields.Many2many("res.groups", string="Additional Groups")
    snapshot_id = fields.Many2one("lab.permission.audit.snapshot", readonly=True)

    def action_generate_snapshot(self):
        for rec in self:
            snap = self.env["lab.permission.audit.snapshot"].create(
                {
                    "include_custom_groups": rec.include_custom_groups,
                    "additional_group_ids": [(6, 0, rec.additional_group_ids.ids)],
                }
            )
            snap.action_generate()
            rec.snapshot_id = snap.id
            return {
                "name": _("Permission Audit Snapshot"),
                "type": "ir.actions.act_window",
                "res_model": "lab.permission.audit.snapshot",
                "res_id": snap.id,
                "view_mode": "form",
                "target": "current",
            }
        return True


class LabInterfaceReconciliationReport(models.Model):
    _name = "lab.interface.reconciliation.report"
    _description = "Interface Reconciliation Report"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True)
    endpoint_id = fields.Many2one("lab.interface.endpoint")

    line_ids = fields.One2many("lab.interface.reconciliation.report.line", "report_id", string="Lines")
    total_lines = fields.Integer(compute="_compute_totals")
    mismatch_lines = fields.Integer(compute="_compute_totals")

    note = fields.Text()

    @api.constrains("period_start", "period_end")
    def _check_period(self):
        for rec in self:
            if rec.period_end < rec.period_start:
                raise ValidationError(_("Period end must be on/after period start."))

    @api.depends("line_ids.is_mismatch")
    def _compute_totals(self):
        for rec in self:
            rec.total_lines = len(rec.line_ids)
            rec.mismatch_lines = len(rec.line_ids.filtered(lambda x: x.is_mismatch))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def _dt_range(self):
        self.ensure_one()
        start = fields.Datetime.to_string(self.period_start)
        end = fields.Datetime.to_string(fields.Date.add(self.period_end, days=1))
        return start, end

    def _job_domain(self):
        self.ensure_one()
        start, end = self._dt_range()
        domain = [
            ("create_date", ">=", start),
            ("create_date", "<", end),
        ]
        if self.endpoint_id:
            domain.append(("endpoint_id", "=", self.endpoint_id.id))
        return domain

    def action_generate(self):
        for rec in self:
            job_obj = self.env["lab.interface.job"]
            sample_obj = self.env["lab.sample"]
            analysis_obj = self.env["lab.sample.analysis"]
            start, end = rec._dt_range()
            jobs = job_obj.search(rec._job_domain())

            outbound_jobs = jobs.filtered(lambda x: x.direction == "outbound")
            inbound_jobs = jobs.filtered(lambda x: x.direction == "inbound")
            outbound_report = outbound_jobs.filtered(lambda x: x.message_type in ("report", "result"))
            inbound_result = inbound_jobs.filtered(lambda x: x.message_type in ("result", "report"))

            expected_report_samples = sample_obj.search_count(
                [
                    ("report_date", ">=", start),
                    ("report_date", "<", end),
                    ("state", "=", "reported"),
                ]
            )
            delivered_report_jobs = len(outbound_report.filtered(lambda x: x.state == "done"))
            expected_result_lines = analysis_obj.search_count(
                [
                    ("state", "in", ("done", "verified")),
                    ("sample_id.received_date", ">=", start),
                    ("sample_id.received_date", "<", end),
                ]
            )
            inbound_result_done = len(inbound_result.filtered(lambda x: x.state == "done"))

            lines = []

            def add_line(code, name, expected, actual, detail=""):
                lines.append(
                    (
                        0,
                        0,
                        {
                            "code": code,
                            "name": name,
                            "expected_value": float(expected),
                            "actual_value": float(actual),
                            "delta_value": float(actual - expected),
                            "is_mismatch": bool(expected != actual),
                            "detail": detail or "",
                        },
                    )
                )

            add_line(
                "outbound_total",
                _("Outbound Jobs Total"),
                len(outbound_jobs),
                len(outbound_jobs),
            )
            add_line(
                "outbound_done",
                _("Outbound Jobs Done"),
                len(outbound_jobs),
                len(outbound_jobs.filtered(lambda x: x.state == "done")),
            )
            add_line(
                "inbound_total",
                _("Inbound Jobs Total"),
                len(inbound_jobs),
                len(inbound_jobs),
            )
            add_line(
                "inbound_done",
                _("Inbound Jobs Done"),
                len(inbound_jobs),
                len(inbound_jobs.filtered(lambda x: x.state == "done")),
            )
            add_line(
                "report_delivery",
                _("Reported Samples vs Delivered Report Jobs"),
                expected_report_samples,
                delivered_report_jobs,
                detail=_("Expected from lab.sample.report_date, actual from outbound report/result done jobs."),
            )
            add_line(
                "result_ingest",
                _("Expected Result Lines vs Inbound Result Jobs"),
                expected_result_lines,
                inbound_result_done,
                detail=_("Expected from analysis done/verified lines in period, actual from inbound result/report jobs."),
            )

            # Detail: missing delivered report per sample
            sample_rows = sample_obj.search(
                [
                    ("report_date", ">=", start),
                    ("report_date", "<", end),
                    ("state", "=", "reported"),
                ],
                order="id asc",
                limit=200,
            )
            for sample in sample_rows:
                sjobs = sample.interface_job_ids.filtered(
                    lambda j: j.direction == "outbound"
                    and j.message_type in ("report", "result")
                    and j.state == "done"
                    and (not rec.endpoint_id or j.endpoint_id == rec.endpoint_id)
                )
                if not sjobs:
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "code": "missing_report_sample",
                                "name": _("Missing report delivery for sample %s") % sample.name,
                                "expected_value": 1.0,
                                "actual_value": 0.0,
                                "delta_value": -1.0,
                                "is_mismatch": True,
                                "detail": _("No outbound done report/result job linked to this sample in selected endpoint scope."),
                                "sample_id": sample.id,
                            },
                        )
                    )

            rec.write({"line_ids": [(5, 0, 0)] + lines})
        return True


class LabInterfaceReconciliationReportLine(models.Model):
    _name = "lab.interface.reconciliation.report.line"
    _description = "Interface Reconciliation Report Line"
    _order = "id"

    report_id = fields.Many2one("lab.interface.reconciliation.report", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    expected_value = fields.Float(required=True)
    actual_value = fields.Float(required=True)
    delta_value = fields.Float(required=True)
    is_mismatch = fields.Boolean(default=False)
    detail = fields.Text()
    sample_id = fields.Many2one("lab.sample", ondelete="set null")


class LabGovernanceWorkbenchWizard(models.TransientModel):
    _name = "lab.governance.workbench.wizard"
    _description = "Governance Workbench"

    period_days = fields.Integer(default=30, required=True)
    task_overdue_count = fields.Integer(readonly=True)
    task_escalated_count = fields.Integer(readonly=True)
    permission_missing_count = fields.Integer(readonly=True)
    interface_mismatch_count = fields.Integer(readonly=True)

    @api.model
    def _compute_metrics_values(self, period_days):
        dt_from = fields.Datetime.now() - timedelta(days=period_days)
        task_obj = self.env["lab.workstation.task"]
        perm_obj = self.env["lab.permission.audit.snapshot"]
        iface_obj = self.env["lab.interface.reconciliation.report"]
        return {
            "task_overdue_count": task_obj.search_count([
                ("state", "=", "overdue"),
                ("create_date", ">=", fields.Datetime.to_string(dt_from)),
            ]),
            "task_escalated_count": task_obj.search_count([
                ("escalated", "=", True),
                ("create_date", ">=", fields.Datetime.to_string(dt_from)),
            ]),
            "permission_missing_count": sum(
                perm_obj.search(
                    [("create_date", ">=", fields.Datetime.to_string(dt_from))]
                ).mapped("missing_count")
            ),
            "interface_mismatch_count": sum(
                iface_obj.search(
                    [("create_date", ">=", fields.Datetime.to_string(dt_from))]
                ).mapped("mismatch_lines")
            ),
        }

    def _compute_metrics(self):
        self.ensure_one()
        return self._compute_metrics_values(self.period_days)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        period_days = vals.get("period_days") or 30
        metrics = self._compute_metrics_values(period_days)
        vals.update({k: v for k, v in metrics.items() if k in fields_list})
        return vals

    def action_refresh(self):
        for rec in self:
            rec.write(rec._compute_metrics())
        return True

    def action_open_overdue_tasks(self):
        return {
            "name": _("Overdue Tasks"),
            "type": "ir.actions.act_window",
            "res_model": "lab.workstation.task",
            "view_mode": "list,form",
            "domain": [("state", "=", "overdue")],
        }

    def action_open_interface_mismatch(self):
        return {
            "name": _("Interface Reconciliation Reports"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.reconciliation.report",
            "view_mode": "list,form",
            "domain": [("mismatch_lines", ">", 0)],
        }


class LabSampleGovernanceMixin(models.Model):
    _inherit = "lab.sample"

    exception_template_count = fields.Integer(compute="_compute_exception_template_count")

    def _compute_exception_template_count(self):
        tmpl_obj = self.env["lab.department.exception.template"]
        for rec in self:
            dept = rec.sop_id.department if rec.sop_id else "other"
            rec.exception_template_count = tmpl_obj.search_count(
                [("active", "=", True), ("department", "=", dept)]
            )

    def action_apply_exception_template(self):
        for rec in self:
            if not rec.sop_id:
                raise UserError(_("Sample has no SOP, cannot apply exception template."))
            template = self.env["lab.department.exception.template"].search(
                [
                    ("active", "=", True),
                    ("department", "=", rec.sop_id.department),
                    ("trigger_event", "=", "manual_review_required"),
                ],
                order="sequence asc, id asc",
                limit=1,
            )
            if not template:
                raise UserError(_("No active exception template found for this department."))
            analysis = rec.analysis_ids.filtered(lambda x: x.needs_manual_review)[:1]
            template.apply_exception(sample=rec, event="manual_review_required", analysis=analysis)
        return True
