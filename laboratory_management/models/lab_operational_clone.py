import json
import statistics
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


DEPARTMENTS = [
    ("chemistry", "Clinical Chemistry"),
    ("hematology", "Hematology"),
    ("microbiology", "Microbiology"),
    ("immunology", "Immunology"),
    ("other", "Other"),
]

ROLE_TYPES = [
    ("reception", "Reception"),
    ("analyst", "Analyst"),
    ("reviewer", "Reviewer"),
    ("manager", "Manager"),
    ("quality", "Quality"),
    ("integration", "Integration"),
]


class LabDepartmentQueueRule(models.Model):
    _name = "lab.department.queue.rule"
    _description = "Department Queue Rule"
    _order = "department, role_type, sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    department = fields.Selection(DEPARTMENTS, required=True)
    role_type = fields.Selection(ROLE_TYPES, required=True)
    priority = fields.Selection(
        [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT"), ("all", "All")],
        default="all",
        required=True,
    )
    source_model = fields.Selection(
        [
            ("lab.sample", "Sample"),
            ("lab.sample.analysis", "Analysis"),
            ("lab.test.request", "Test Request"),
            ("lab.interface.job", "Interface Job"),
            ("lab.nonconformance", "Nonconformance"),
        ],
        required=True,
    )
    source_state = fields.Char(
        required=True,
        help="Comma separated states, e.g. draft,in_progress,to_verify",
    )
    include_overdue_only = fields.Boolean(default=False)
    include_critical_only = fields.Boolean(default=False)
    include_manual_review_only = fields.Boolean(default=False)
    include_failed_only = fields.Boolean(default=False)
    domain_json = fields.Text(
        help="Optional JSON domain list, merged with rule domain. Example: [[\"request_type\",\"=\",\"institution\"]]",
    )
    action_name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    note = fields.Text()

    def _base_domain(self):
        self.ensure_one()
        states = [x.strip() for x in (self.source_state or "").split(",") if x.strip()]
        domain = []
        if self.source_model == "lab.sample":
            if states:
                domain.append(("state", "in", states))
            if self.priority != "all":
                domain.append(("priority", "=", self.priority))
            if self.include_overdue_only:
                domain.append(("is_overdue", "=", True))
        elif self.source_model == "lab.sample.analysis":
            if states:
                domain.append(("state", "in", states))
            domain.append(("department", "=", self.department))
            if self.include_critical_only:
                domain.append(("is_critical", "=", True))
            if self.include_manual_review_only:
                domain.append(("needs_manual_review", "=", True))
            if self.include_overdue_only:
                domain.append(("review_overdue", "=", True))
        elif self.source_model == "lab.test.request":
            if states:
                domain.append(("state", "in", states))
            if self.priority != "all":
                domain.append(("priority", "=", self.priority))
        elif self.source_model == "lab.interface.job":
            if states:
                domain.append(("state", "in", states))
            if self.include_failed_only:
                domain.append(("state", "in", ("failed", "dead_letter")))
        elif self.source_model == "lab.nonconformance":
            if states:
                domain.append(("state", "in", states))
            if self.include_overdue_only:
                domain.append(("due_date", "<", fields.Date.today()))

        if self.domain_json:
            try:
                extra = json.loads(self.domain_json)
                if isinstance(extra, list):
                    domain += [tuple(x) for x in extra if isinstance(x, (list, tuple)) and len(x) == 3]
            except Exception:  # noqa: BLE001
                pass
        return domain

    def action_open_records(self):
        self.ensure_one()
        return {
            "name": self.action_name,
            "type": "ir.actions.act_window",
            "res_model": self.source_model,
            "view_mode": "list,form",
            "domain": self._base_domain(),
        }


class LabDepartmentWorkbenchWizard(models.TransientModel):
    _name = "lab.department.workbench.wizard"
    _description = "Department Role Workbench"

    department = fields.Selection(DEPARTMENTS, required=True, default="chemistry")
    role_type = fields.Selection(ROLE_TYPES, required=True, default="analyst")

    queue_total = fields.Integer(readonly=True)
    overdue_total = fields.Integer(readonly=True)
    critical_total = fields.Integer(readonly=True)
    manual_review_total = fields.Integer(readonly=True)
    failed_interface_total = fields.Integer(readonly=True)
    ncr_open_total = fields.Integer(readonly=True)

    rule_result_json = fields.Text(readonly=True)

    def _query_metrics(self):
        self.ensure_one()
        sample_obj = self.env["lab.sample"]
        analysis_obj = self.env["lab.sample.analysis"]
        iface_obj = self.env["lab.interface.job"]
        ncr_obj = self.env["lab.nonconformance"]

        return {
            "queue_total": sample_obj.search_count(
                [
                    ("state", "in", ("draft", "received", "in_progress", "to_verify")),
                    ("analysis_ids.department", "=", self.department),
                ]
            ),
            "overdue_total": sample_obj.search_count(
                [
                    ("is_overdue", "=", True),
                    ("analysis_ids.department", "=", self.department),
                ]
            ),
            "critical_total": analysis_obj.search_count(
                [
                    ("department", "=", self.department),
                    ("is_critical", "=", True),
                    ("state", "in", ("assigned", "done", "verified")),
                ]
            ),
            "manual_review_total": analysis_obj.search_count(
                [
                    ("department", "=", self.department),
                    ("needs_manual_review", "=", True),
                    ("state", "in", ("assigned", "done")),
                ]
            ),
            "failed_interface_total": iface_obj.search_count(
                [("state", "in", ("failed", "dead_letter"))]
            ),
            "ncr_open_total": ncr_obj.search_count(
                [("state", "in", ("open", "investigation", "capa"))]
            ),
        }

    def _rule_results(self):
        self.ensure_one()
        rules = self.env["lab.department.queue.rule"].search(
            [
                ("active", "=", True),
                ("department", "=", self.department),
                ("role_type", "=", self.role_type),
            ],
            order="sequence asc, id asc",
        )
        rows = []
        for rule in rules:
            count = self.env[rule.source_model].search_count(rule._base_domain())
            rows.append(
                {
                    "rule_id": rule.id,
                    "name": rule.name,
                    "source_model": rule.source_model,
                    "action_name": rule.action_name,
                    "count": count,
                }
            )
        return rows

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        rec = self.new(vals)
        metrics = rec._query_metrics()
        rule_rows = rec._rule_results()
        metrics["rule_result_json"] = json.dumps(rule_rows, ensure_ascii=False, indent=2)
        vals.update({k: metrics[k] for k in metrics if k in fields_list})
        return vals

    def action_refresh(self):
        for rec in self:
            metrics = rec._query_metrics()
            metrics["rule_result_json"] = json.dumps(rec._rule_results(), ensure_ascii=False, indent=2)
            rec.write(metrics)
        return True

    def _open_with_domain(self, model_name, domain, title):
        return {
            "name": title,
            "type": "ir.actions.act_window",
            "res_model": model_name,
            "view_mode": "list,form",
            "domain": domain,
        }

    def action_open_queue(self):
        self.ensure_one()
        return self._open_with_domain(
            "lab.sample",
            [
                ("state", "in", ("draft", "received", "in_progress", "to_verify")),
                ("analysis_ids.department", "=", self.department),
            ],
            _("Department Queue"),
        )

    def action_open_overdue(self):
        self.ensure_one()
        return self._open_with_domain(
            "lab.sample",
            [("is_overdue", "=", True), ("analysis_ids.department", "=", self.department)],
            _("Department Overdue"),
        )

    def action_open_critical(self):
        self.ensure_one()
        return self._open_with_domain(
            "lab.sample.analysis",
            [
                ("department", "=", self.department),
                ("is_critical", "=", True),
                ("state", "in", ("assigned", "done", "verified")),
            ],
            _("Department Critical Results"),
        )

    def action_open_manual_review(self):
        self.ensure_one()
        return self._open_with_domain(
            "lab.sample.analysis",
            [
                ("department", "=", self.department),
                ("needs_manual_review", "=", True),
                ("state", "in", ("assigned", "done")),
            ],
            _("Department Manual Review"),
        )

    def action_open_failed_interface(self):
        return self._open_with_domain(
            "lab.interface.job",
            [("state", "in", ("failed", "dead_letter"))],
            _("Failed Interface Jobs"),
        )

    def action_open_ncr(self):
        return self._open_with_domain(
            "lab.nonconformance",
            [("state", "in", ("open", "investigation", "capa"))],
            _("Open NCR"),
        )


class LabHl7Template(models.Model):
    _name = "lab.hl7.template"
    _description = "HL7 Template"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    message_type = fields.Selection(
        [("order", "Order ORM^O01"), ("result", "Result ORU^R01"), ("ack", "ACK")],
        default="order",
        required=True,
    )
    version = fields.Char(default="2.5")
    active = fields.Boolean(default=True)
    segment_ids = fields.One2many("lab.hl7.template.segment", "template_id", string="Segments")
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "HL7 template code must be unique.")

    def _render_segment(self, segment, context_values):
        row = segment.segment_name
        values = [x.strip() for x in (segment.field_template or "").split("|")]
        rendered = []
        for token in values:
            if not token:
                rendered.append("")
                continue
            out = token
            for k, v in context_values.items():
                out = out.replace("{{%s}}" % k, str(v if v is not None else ""))
            rendered.append(out)
        return row + "|" + "|".join(rendered)

    def render_message(self, context_values):
        self.ensure_one()
        if not self.segment_ids:
            raise ValidationError(_("HL7 template requires at least one segment."))
        lines = []
        for seg in self.segment_ids.sorted("sequence"):
            if seg.segment_name == "OBX" and context_values.get("obx_rows"):
                for item in context_values["obx_rows"]:
                    merged = dict(context_values)
                    merged.update(item)
                    lines.append(self._render_segment(seg, merged))
                continue
            lines.append(self._render_segment(seg, context_values))
        return "\r".join(lines) + "\r"


class LabHl7TemplateSegment(models.Model):
    _name = "lab.hl7.template.segment"
    _description = "HL7 Template Segment"
    _order = "template_id, sequence, id"

    sequence = fields.Integer(default=10)
    template_id = fields.Many2one("lab.hl7.template", required=True, ondelete="cascade", index=True)
    segment_name = fields.Selection(
        [("MSH", "MSH"), ("PID", "PID"), ("ORC", "ORC"), ("OBR", "OBR"), ("OBX", "OBX"), ("MSA", "MSA")],
        required=True,
    )
    field_template = fields.Text(
        required=True,
        help="Use placeholders like {{control_id}}, {{patient_name}}, {{service_code}}, {{result_value}}",
    )
    repeatable = fields.Boolean(default=False)
    note = fields.Char()


class LabQcTrendProfile(models.Model):
    _name = "lab.qc.trend.profile"
    _description = "QC Trend Profile"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    service_ids = fields.Many2many("lab.service", string="Services")
    window_size = fields.Integer(default=20)
    warning_sigma = fields.Float(default=2.0)
    reject_sigma = fields.Float(default=3.0)
    active = fields.Boolean(default=True)
    note = fields.Text()

    _qc_trend_profile_code_uniq = models.Constraint("unique(code)", "QC trend profile code must be unique.")


class LabQcTrendSnapshot(models.Model):
    _name = "lab.qc.trend.snapshot"
    _description = "QC Trend Snapshot"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "captured_at desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    profile_id = fields.Many2one("lab.qc.trend.profile", required=True, ondelete="restrict", index=True)
    captured_at = fields.Datetime(default=fields.Datetime.now, required=True)
    line_ids = fields.One2many("lab.qc.trend.snapshot.line", "snapshot_id", string="Lines")
    total_service = fields.Integer(compute="_compute_stats")
    warning_count = fields.Integer(compute="_compute_stats")
    reject_count = fields.Integer(compute="_compute_stats")
    state = fields.Selection(
        [("draft", "Draft"), ("captured", "Captured"), ("published", "Published")],
        default="draft",
        tracking=True,
    )
    summary = fields.Text()

    @api.depends("line_ids.status")
    def _compute_stats(self):
        for rec in self:
            rec.total_service = len(rec.line_ids)
            rec.warning_count = len(rec.line_ids.filtered(lambda x: x.status == "warning"))
            rec.reject_count = len(rec.line_ids.filtered(lambda x: x.status == "reject"))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.kpi.snapshot") or "New"
        return super().create(vals_list)

    def _service_qc_values(self, service, limit_size):
        rows = self.env["lab.qc.run"].search(
            [("service_id", "=", service.id)],
            order="run_date desc, id desc",
            limit=limit_size,
        )
        return [x.result_value for x in rows if x.result_value not in (None, False)]

    def action_capture(self):
        for rec in self:
            profile = rec.profile_id
            services = profile.service_ids or self.env["lab.service"].search([])
            lines = []
            for service in services:
                values = rec._service_qc_values(service, profile.window_size)
                if not values:
                    continue
                mean_val = statistics.mean(values)
                std_val = statistics.pstdev(values) if len(values) > 1 else 0.0
                latest = values[0]
                sigma = abs((latest - mean_val) / std_val) if std_val else 0.0
                if sigma >= profile.reject_sigma:
                    status = "reject"
                elif sigma >= profile.warning_sigma:
                    status = "warning"
                else:
                    status = "pass"
                lines.append(
                    (
                        0,
                        0,
                        {
                            "service_id": service.id,
                            "sample_size": len(values),
                            "latest_value": latest,
                            "mean_value": mean_val,
                            "std_value": std_val,
                            "sigma_value": sigma,
                            "status": status,
                        },
                    )
                )
            rec.write({"line_ids": [(5, 0, 0)] + lines, "state": "captured"})
        return True

    def action_publish(self):
        self.write({"state": "published"})
        return True


class LabQcTrendSnapshotLine(models.Model):
    _name = "lab.qc.trend.snapshot.line"
    _description = "QC Trend Snapshot Line"
    _order = "id"

    snapshot_id = fields.Many2one("lab.qc.trend.snapshot", required=True, ondelete="cascade", index=True)
    service_id = fields.Many2one("lab.service", required=True)
    sample_size = fields.Integer(required=True)
    latest_value = fields.Float(required=True)
    mean_value = fields.Float(required=True)
    std_value = fields.Float(required=True)
    sigma_value = fields.Float(required=True)
    status = fields.Selection(
        [("pass", "Pass"), ("warning", "Warning"), ("reject", "Reject")],
        required=True,
    )
    comment = fields.Char()


class LabComplianceAuditReport(models.Model):
    _name = "lab.compliance.audit.report"
    _description = "Compliance Audit Report"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True)
    department = fields.Selection(DEPARTMENTS)
    line_ids = fields.One2many("lab.compliance.audit.report.line", "report_id", string="Sections")
    state = fields.Selection(
        [("draft", "Draft"), ("generated", "Generated"), ("approved", "Approved")],
        default="draft",
        tracking=True,
    )
    generated_at = fields.Datetime(readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approved_by_id = fields.Many2one("res.users", readonly=True)
    conclusion = fields.Text()

    @api.constrains("period_start", "period_end")
    def _check_period(self):
        for rec in self:
            if rec.period_end < rec.period_start:
                raise ValidationError(_("Period end must be on/after period start."))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def _date_domain(self):
        self.ensure_one()
        start = fields.Datetime.to_string(self.period_start)
        end = fields.Datetime.to_string(fields.Date.add(self.period_end, days=1))
        return [("create_date", ">=", start), ("create_date", "<", end)]

    def action_generate(self):
        for rec in self:
            domain = rec._date_domain()
            if rec.department:
                sample_domain = domain + [("analysis_ids.department", "=", rec.department)]
                analysis_domain = domain + [("department", "=", rec.department)]
            else:
                sample_domain = domain
                analysis_domain = domain

            total_samples = self.env["lab.sample"].search_count(sample_domain)
            reported_samples = self.env["lab.sample"].search_count(sample_domain + [("state", "=", "reported")])
            overdue_samples = self.env["lab.sample"].search_count(sample_domain + [("is_overdue", "=", True)])
            critical_lines = self.env["lab.sample.analysis"].search_count(
                analysis_domain + [("is_critical", "=", True)]
            )
            manual_review = self.env["lab.sample.analysis"].search_count(
                analysis_domain + [("needs_manual_review", "=", True)]
            )
            ncr_open = self.env["lab.nonconformance"].search_count(
                domain + [("state", "in", ("open", "investigation", "capa"))]
            )
            iface_fail = self.env["lab.interface.job"].search_count(
                domain + [("state", "in", ("failed", "dead_letter"))]
            )

            on_time_rate = (100.0 * reported_samples / total_samples) if total_samples else 0.0
            overdue_rate = (100.0 * overdue_samples / total_samples) if total_samples else 0.0

            sections = [
                {
                    "code": "sample_flow",
                    "name": _("Sample Flow"),
                    "metric_value": on_time_rate,
                    "target_value": 95.0,
                    "unit": "%",
                    "risk_level": "high" if on_time_rate < 90 else ("medium" if on_time_rate < 95 else "low"),
                    "detail": _(
                        "Total samples: %(total)s, reported: %(reported)s, overdue: %(overdue)s"
                    )
                    % {
                        "total": total_samples,
                        "reported": reported_samples,
                        "overdue": overdue_samples,
                    },
                },
                {
                    "code": "turnaround_overdue",
                    "name": _("Turnaround Overdue Rate"),
                    "metric_value": overdue_rate,
                    "target_value": 3.0,
                    "unit": "%",
                    "risk_level": "high" if overdue_rate > 10 else ("medium" if overdue_rate > 3 else "low"),
                    "detail": _("Overdue samples %s") % overdue_samples,
                },
                {
                    "code": "critical_result",
                    "name": _("Critical Results"),
                    "metric_value": float(critical_lines),
                    "target_value": 0.0,
                    "unit": "count",
                    "risk_level": "medium" if critical_lines else "low",
                    "detail": _("Critical analysis lines %s") % critical_lines,
                },
                {
                    "code": "manual_review",
                    "name": _("Manual Review Queue"),
                    "metric_value": float(manual_review),
                    "target_value": 5.0,
                    "unit": "count",
                    "risk_level": "high" if manual_review > 20 else ("medium" if manual_review > 5 else "low"),
                    "detail": _("Manual review lines %s") % manual_review,
                },
                {
                    "code": "ncr_open",
                    "name": _("Open NCR"),
                    "metric_value": float(ncr_open),
                    "target_value": 3.0,
                    "unit": "count",
                    "risk_level": "high" if ncr_open > 10 else ("medium" if ncr_open > 3 else "low"),
                    "detail": _("Open nonconformances %s") % ncr_open,
                },
                {
                    "code": "interface_fail",
                    "name": _("Interface Failure"),
                    "metric_value": float(iface_fail),
                    "target_value": 0.0,
                    "unit": "count",
                    "risk_level": "high" if iface_fail > 3 else ("medium" if iface_fail else "low"),
                    "detail": _("Failed/dead-letter interface jobs %s") % iface_fail,
                },
            ]

            rec.write(
                {
                    "line_ids": [
                        (0, 0, x)
                        for x in sections
                    ],
                    "generated_at": fields.Datetime.now(),
                    "state": "generated",
                }
            )
        return True

    def action_approve(self):
        self.write(
            {
                "state": "approved",
                "approved_at": fields.Datetime.now(),
                "approved_by_id": self.env.user.id,
            }
        )
        return True


class LabComplianceAuditReportLine(models.Model):
    _name = "lab.compliance.audit.report.line"
    _description = "Compliance Audit Report Section"
    _order = "id"

    report_id = fields.Many2one("lab.compliance.audit.report", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    metric_value = fields.Float(required=True)
    target_value = fields.Float(required=True)
    unit = fields.Char(default="%")
    risk_level = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High")],
        required=True,
    )
    is_pass = fields.Boolean(compute="_compute_is_pass", store=True)
    detail = fields.Text()

    @api.depends("metric_value", "target_value", "code")
    def _compute_is_pass(self):
        reverse_codes = {"turnaround_overdue", "ncr_open", "interface_fail"}
        for rec in self:
            if rec.code in reverse_codes:
                rec.is_pass = rec.metric_value <= rec.target_value
            else:
                rec.is_pass = rec.metric_value >= rec.target_value


class LabServiceOperationalMixin(models.Model):
    _inherit = "lab.service"

    queue_rule_ids = fields.Many2many("lab.department.queue.rule", string="Queue Rules")


class LabInterfaceEndpointOperationalMixin(models.Model):
    _inherit = "lab.interface.endpoint"

    hl7_order_template_id = fields.Many2one(
        "lab.hl7.template",
        domain="[('message_type','=','order'), ('active','=',True)]",
        string="HL7 Order Template",
    )
    hl7_result_template_id = fields.Many2one(
        "lab.hl7.template",
        domain="[('message_type','=','result'), ('active','=',True)]",
        string="HL7 Result Template",
    )


class LabInterfaceJobOperationalMixin(models.Model):
    _inherit = "lab.interface.job"

    def _simulate_dispatch(self, payload):
        self.ensure_one()
        if self.endpoint_id.protocol == "hl7v2":
            template = False
            if self.message_type == "order":
                template = self.endpoint_id.hl7_order_template_id
            elif self.message_type in ("result", "report"):
                template = self.endpoint_id.hl7_result_template_id

            if template:
                base_context = {
                    "control_id": self.name,
                    "message_time": fields.Datetime.now().strftime("%Y%m%d%H%M%S"),
                    "patient_name": payload.get("patient_name") or "UNKNOWN^PATIENT",
                    "request_no": payload.get("request_no") or payload.get("request") or "",
                    "accession": payload.get("accession") or payload.get("sample") or "",
                    "service_code": "",
                    "result_value": "",
                    "result_flag": "",
                }
                obx_rows = []
                for row in payload.get("results") or []:
                    obx_rows.append(
                        {
                            "service_code": row.get("service_code") or "",
                            "result_value": row.get("result") or "",
                            "result_flag": row.get("flag") or "",
                        }
                    )
                if not obx_rows and (payload.get("lines") or []):
                    for row in payload.get("lines"):
                        obx_rows.append({"service_code": row.get("service_code") or "", "result_value": "", "result_flag": ""})

                context_values = dict(base_context)
                context_values["obx_rows"] = obx_rows
                msg = template.render_message(context_values)
                return "200", "AA|%s\n%s" % (self.name, msg)

        return super()._simulate_dispatch(payload)


class LabDepartmentWorkbenchRuleRun(models.Model):
    _name = "lab.department.workbench.rule.run"
    _description = "Workbench Rule Run"
    _order = "id desc"

    wizard_department = fields.Selection(DEPARTMENTS, required=True)
    wizard_role_type = fields.Selection(ROLE_TYPES, required=True)
    rule_id = fields.Many2one("lab.department.queue.rule", required=True, ondelete="cascade")
    run_at = fields.Datetime(default=fields.Datetime.now, required=True)
    result_count = fields.Integer(required=True)


class LabDepartmentWorkbenchWizardRunMixin(models.TransientModel):
    _inherit = "lab.department.workbench.wizard"

    def action_log_rule_runs(self):
        self.ensure_one()
        rules = self.env["lab.department.queue.rule"].search(
            [
                ("active", "=", True),
                ("department", "=", self.department),
                ("role_type", "=", self.role_type),
            ]
        )
        rows = []
        for rule in rules:
            count = self.env[rule.source_model].search_count(rule._base_domain())
            rows.append(
                {
                    "wizard_department": self.department,
                    "wizard_role_type": self.role_type,
                    "rule_id": rule.id,
                    "result_count": count,
                }
            )
        if rows:
            self.env["lab.department.workbench.rule.run"].create(rows)
        return True


class LabOperationalControlMixin(models.AbstractModel):
    _name = "lab.operational.control.mixin"
    _description = "Operational Control Mixin"

    @api.model
    def _cron_capture_department_workbench_runs(self):
        rule_obj = self.env["lab.department.queue.rule"]
        run_obj = self.env["lab.department.workbench.rule.run"]
        rules = rule_obj.search([("active", "=", True)])
        rows = []
        for rule in rules:
            count = self.env[rule.source_model].search_count(rule._base_domain())
            rows.append(
                {
                    "wizard_department": rule.department,
                    "wizard_role_type": rule.role_type,
                    "rule_id": rule.id,
                    "result_count": count,
                }
            )
        if rows:
            run_obj.create(rows)
        return True


class LabInterfaceAnalyticsReport(models.Model):
    _name = "lab.interface.analytics.report"
    _description = "Interface Analytics Report"
    _order = "period_end desc, id desc"

    period_start = fields.Date(required=True)
    period_end = fields.Date(required=True)
    endpoint_id = fields.Many2one("lab.interface.endpoint")
    total_jobs = fields.Integer(readonly=True)
    done_jobs = fields.Integer(readonly=True)
    failed_jobs = fields.Integer(readonly=True)
    dead_letter_jobs = fields.Integer(readonly=True)
    inbound_jobs = fields.Integer(readonly=True)
    outbound_jobs = fields.Integer(readonly=True)
    unique_external_uid = fields.Integer(readonly=True)
    success_rate = fields.Float(readonly=True)
    report_json = fields.Text(readonly=True)

    def action_generate(self):
        for rec in self:
            if rec.period_end < rec.period_start:
                raise UserError(_("Invalid period range."))
            domain = [
                ("create_date", ">=", fields.Datetime.to_string(rec.period_start)),
                ("create_date", "<", fields.Datetime.to_string(fields.Date.add(rec.period_end, days=1))),
            ]
            if rec.endpoint_id:
                domain.append(("endpoint_id", "=", rec.endpoint_id.id))

            job_obj = self.env["lab.interface.job"]
            jobs = job_obj.search(domain)
            total = len(jobs)
            done = len(jobs.filtered(lambda x: x.state == "done"))
            failed = len(jobs.filtered(lambda x: x.state == "failed"))
            dead = len(jobs.filtered(lambda x: x.state == "dead_letter"))
            inbound = len(jobs.filtered(lambda x: x.direction == "inbound"))
            outbound = len(jobs.filtered(lambda x: x.direction == "outbound"))
            ext_uid = len(set([x.external_uid for x in jobs if x.external_uid]))
            success_rate = (100.0 * done / total) if total else 0.0

            by_endpoint = defaultdict(lambda: {"total": 0, "done": 0, "failed": 0, "dead": 0})
            for job in jobs:
                key = job.endpoint_id.code if job.endpoint_id else "UNKNOWN"
                by_endpoint[key]["total"] += 1
                if job.state == "done":
                    by_endpoint[key]["done"] += 1
                if job.state == "failed":
                    by_endpoint[key]["failed"] += 1
                if job.state == "dead_letter":
                    by_endpoint[key]["dead"] += 1

            rec.write(
                {
                    "total_jobs": total,
                    "done_jobs": done,
                    "failed_jobs": failed,
                    "dead_letter_jobs": dead,
                    "inbound_jobs": inbound,
                    "outbound_jobs": outbound,
                    "unique_external_uid": ext_uid,
                    "success_rate": success_rate,
                    "report_json": json.dumps(by_endpoint, ensure_ascii=False, indent=2),
                }
            )
        return True
