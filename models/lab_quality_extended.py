from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabEqaScheme(models.Model):
    _name = "lab.eqa.scheme"
    _description = "External Quality Assessment Scheme"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    provider = fields.Char(required=True)
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
    service_ids = fields.Many2many("lab.service", string="Covered Services")
    active = fields.Boolean(default=True)
    round_ids = fields.One2many("lab.eqa.round", "scheme_id", string="Rounds", readonly=True)
    note = fields.Text()

    _code_uniq = models.Constraint("unique(code)", "EQA scheme code must be unique.")


class LabEqaRound(models.Model):
    _name = "lab.eqa.round"
    _description = "EQA Round"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sample_date desc, id desc"

    name = fields.Char(required=True)
    scheme_id = fields.Many2one("lab.eqa.scheme", required=True, ondelete="cascade")
    sample_date = fields.Date(required=True, default=fields.Date.today)
    due_date = fields.Date()
    submitted_date = fields.Date()
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"), ("evaluated", "Evaluated"), ("closed", "Closed")],
        default="draft",
        tracking=True,
    )
    result_ids = fields.One2many("lab.eqa.result", "round_id", string="Results")
    pass_rate = fields.Float(compute="_compute_result_stats", store=True)
    fail_count = fields.Integer(compute="_compute_result_stats", store=True)
    zscore_mean = fields.Float(compute="_compute_result_stats", store=True)
    note = fields.Text()

    @api.depends("result_ids.status", "result_ids.z_score")
    def _compute_result_stats(self):
        for rec in self:
            total = len(rec.result_ids)
            passed = len(rec.result_ids.filtered(lambda r: r.status == "pass"))
            rec.fail_count = len(rec.result_ids.filtered(lambda r: r.status == "fail"))
            rec.pass_rate = (100.0 * passed / total) if total else 0.0
            z_scores = [abs(r.z_score) for r in rec.result_ids if r.z_score]
            rec.zscore_mean = (sum(z_scores) / len(z_scores)) if z_scores else 0.0

    def action_submit(self):
        for rec in self:
            if not rec.result_ids:
                raise UserError(_("Please add EQA results before submit."))
            rec.write({"state": "submitted", "submitted_date": fields.Date.today()})
        return True

    def action_evaluate(self):
        for rec in self:
            rec.result_ids._compute_status()
            rec.state = "evaluated"
        return True

    def action_close(self):
        for rec in self:
            if rec.state != "evaluated":
                raise UserError(_("EQA round must be evaluated before close."))
            rec.state = "closed"
        return True

    @api.constrains("due_date", "sample_date")
    def _check_dates(self):
        for rec in self:
            if rec.due_date and rec.due_date < rec.sample_date:
                raise ValidationError(_("Due date must be after sample date."))


class LabEqaResult(models.Model):
    _name = "lab.eqa.result"
    _description = "EQA Result"
    _order = "id"

    round_id = fields.Many2one("lab.eqa.round", required=True, ondelete="cascade")
    service_id = fields.Many2one("lab.service", required=True)
    expected_value = fields.Float(required=True)
    reported_value = fields.Float(required=True)
    tolerance = fields.Float(default=2.0, help="Acceptable absolute z-score boundary.")
    z_score = fields.Float(compute="_compute_status", store=True)
    status = fields.Selection([("pass", "Pass"), ("fail", "Fail")], compute="_compute_status", store=True)
    note = fields.Text()

    @api.depends("expected_value", "reported_value", "tolerance")
    def _compute_status(self):
        for rec in self:
            denominator = abs(rec.expected_value) or 1.0
            z = (rec.reported_value - rec.expected_value) / denominator
            rec.z_score = z
            rec.status = "pass" if abs(z) <= (rec.tolerance or 2.0) else "fail"


class LabComplianceSnapshot(models.Model):
    _name = "lab.compliance.snapshot"
    _description = "Compliance Snapshot"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_end desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    period_start = fields.Date(required=True, default=lambda self: fields.Date.today().replace(day=1))
    period_end = fields.Date(required=True, default=fields.Date.today)
    generated_at = fields.Datetime(readonly=True)
    generated_by_id = fields.Many2one("res.users", readonly=True)

    total_samples = fields.Integer(readonly=True)
    reported_samples = fields.Integer(readonly=True)
    overdue_samples = fields.Integer(readonly=True)
    on_time_rate = fields.Float(readonly=True)

    qc_total = fields.Integer(readonly=True)
    qc_reject = fields.Integer(readonly=True)
    qc_reject_rate = fields.Float(readonly=True)

    eqa_total = fields.Integer(readonly=True)
    eqa_pass = fields.Integer(readonly=True)
    eqa_pass_rate = fields.Float(readonly=True)

    ncr_total = fields.Integer(readonly=True)
    ncr_closed = fields.Integer(readonly=True)
    ncr_closure_rate = fields.Float(readonly=True)

    interface_total = fields.Integer(readonly=True)
    interface_success = fields.Integer(readonly=True)
    interface_success_rate = fields.Float(readonly=True)
    line_ids = fields.One2many("lab.compliance.snapshot.line", "snapshot_id", string="Detailed Lines")
    state = fields.Selection([("draft", "Draft"), ("published", "Published")], default="draft")
    conclusion = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = "CMP/%s" % fields.Datetime.now().strftime("%Y%m%d%H%M%S")
        return super().create(vals_list)

    def action_generate(self):
        sample_obj = self.env["lab.sample"]
        qc_obj = self.env["lab.qc.run"]
        eqa_obj = self.env["lab.eqa.result"]
        ncr_obj = self.env["lab.nonconformance"]
        iface_obj = self.env["lab.interface.job"]
        for rec in self:
            if rec.period_end < rec.period_start:
                raise UserError(_("Period end must be after period start."))

            start_dt = fields.Datetime.to_string(rec.period_start)
            end_dt = fields.Datetime.to_string(fields.Date.add(rec.period_end, days=1))

            sample_domain = [("create_date", ">=", start_dt), ("create_date", "<", end_dt)]
            qc_domain = [("create_date", ">=", start_dt), ("create_date", "<", end_dt)]
            eqa_domain = [("create_date", ">=", start_dt), ("create_date", "<", end_dt)]
            ncr_domain = [("create_date", ">=", start_dt), ("create_date", "<", end_dt)]
            iface_domain = [("create_date", ">=", start_dt), ("create_date", "<", end_dt)]

            total_samples = sample_obj.search_count(sample_domain)
            reported_samples = sample_obj.search_count(sample_domain + [("state", "=", "reported")])
            overdue_samples = sample_obj.search_count(sample_domain + [("is_overdue", "=", True)])
            on_time_rate = (100.0 * reported_samples / total_samples) if total_samples else 0.0

            qc_total = qc_obj.search_count(qc_domain)
            qc_reject = qc_obj.search_count(qc_domain + [("status", "=", "reject")])
            qc_reject_rate = (100.0 * qc_reject / qc_total) if qc_total else 0.0

            eqa_total = eqa_obj.search_count(eqa_domain)
            eqa_pass = eqa_obj.search_count(eqa_domain + [("status", "=", "pass")])
            eqa_pass_rate = (100.0 * eqa_pass / eqa_total) if eqa_total else 0.0

            ncr_total = ncr_obj.search_count(ncr_domain)
            ncr_closed = ncr_obj.search_count(ncr_domain + [("state", "=", "closed")])
            ncr_closure_rate = (100.0 * ncr_closed / ncr_total) if ncr_total else 0.0

            interface_total = iface_obj.search_count(iface_domain)
            interface_success = iface_obj.search_count(iface_domain + [("state", "=", "done")])
            interface_success_rate = (100.0 * interface_success / interface_total) if interface_total else 0.0

            rec.write(
                {
                    "generated_at": fields.Datetime.now(),
                    "generated_by_id": self.env.user.id,
                    "total_samples": total_samples,
                    "reported_samples": reported_samples,
                    "overdue_samples": overdue_samples,
                    "on_time_rate": on_time_rate,
                    "qc_total": qc_total,
                    "qc_reject": qc_reject,
                    "qc_reject_rate": qc_reject_rate,
                    "eqa_total": eqa_total,
                    "eqa_pass": eqa_pass,
                    "eqa_pass_rate": eqa_pass_rate,
                    "ncr_total": ncr_total,
                    "ncr_closed": ncr_closed,
                    "ncr_closure_rate": ncr_closure_rate,
                    "interface_total": interface_total,
                    "interface_success": interface_success,
                    "interface_success_rate": interface_success_rate,
                    "line_ids": [(5, 0, 0)],
                }
            )
            rec._write_default_lines()
        return True

    def _write_default_lines(self):
        for rec in self:
            lines = [
                ("sample_turnaround", _("On-time report rate"), rec.on_time_rate, 95.0, "%"),
                ("qc_reject_rate", _("QC reject rate"), rec.qc_reject_rate, 3.0, "%"),
                ("eqa_pass_rate", _("EQA pass rate"), rec.eqa_pass_rate, 90.0, "%"),
                ("ncr_closure_rate", _("NCR closure rate"), rec.ncr_closure_rate, 85.0, "%"),
                ("interface_success_rate", _("Interface success rate"), rec.interface_success_rate, 98.0, "%"),
            ]
            rec.write(
                {
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "code": code,
                                "name": name,
                                "actual_value": actual,
                                "target_value": target,
                                "unit": unit,
                            },
                        )
                        for code, name, actual, target, unit in lines
                    ]
                }
            )

    def action_publish(self):
        self.write({"state": "published"})
        return True

    @api.model
    def _cron_generate_monthly_snapshot(self):
        today = fields.Date.today()
        month_start = today.replace(day=1)
        snapshot = self.create({"period_start": month_start, "period_end": today})
        snapshot.action_generate()
        snapshot.action_publish()
        return True


class LabComplianceSnapshotLine(models.Model):
    _name = "lab.compliance.snapshot.line"
    _description = "Compliance Snapshot Line"
    _order = "id"

    snapshot_id = fields.Many2one("lab.compliance.snapshot", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    actual_value = fields.Float(required=True)
    target_value = fields.Float(required=True)
    unit = fields.Char(default="%")
    passed = fields.Boolean(compute="_compute_passed", store=True)
    gap = fields.Float(compute="_compute_passed", store=True)
    note = fields.Text()

    @api.depends("actual_value", "target_value")
    def _compute_passed(self):
        lower_is_better = {"qc_reject_rate"}
        for rec in self:
            if rec.code in lower_is_better:
                rec.passed = rec.actual_value <= rec.target_value
                rec.gap = rec.target_value - rec.actual_value
            else:
                rec.passed = rec.actual_value >= rec.target_value
                rec.gap = rec.actual_value - rec.target_value
