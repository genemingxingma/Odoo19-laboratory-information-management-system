import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabQcMaterial(models.Model):
    _name = "lab.qc.material"
    _description = "QC Material"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    service_id = fields.Many2one("lab.service", required=True)
    lot_number = fields.Char()
    target_value = fields.Float(required=True)
    std_dev = fields.Float(required=True, default=1.0)
    active = fields.Boolean(default=True)
    note = fields.Text()
    rule_ids = fields.Many2many(
        "lab.qc.rule.library",
        "lab_qc_material_rule_rel",
        "material_id",
        "rule_id",
        string="Westgard Rules",
        domain=[("active", "=", True)],
        help="If empty, all active rules from library are used.",
    )
    trend_json = fields.Text(
        compute="_compute_trend_json",
        help="JSON payload for UI trend chart rendering of latest QC runs.",
    )

    def _compute_trend_json(self):
        for rec in self:
            rows = self.env["lab.qc.run"].search(
                [("qc_material_id", "=", rec.id)],
                order="run_date desc, id desc",
                limit=30,
            )
            rows = rows.sorted("run_date")
            points = [
                {
                    "x": fields.Datetime.to_string(r.run_date),
                    "value": r.result_value,
                    "z": r.z_score,
                    "status": r.status,
                }
                for r in rows
            ]
            rec.trend_json = json.dumps(points, ensure_ascii=True)


class LabQcRun(models.Model):
    _name = "lab.qc.run"
    _description = "QC Run"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    qc_material_id = fields.Many2one("lab.qc.material", required=True)
    service_id = fields.Many2one(related="qc_material_id.service_id", store=True)
    run_date = fields.Datetime(default=fields.Datetime.now, required=True)
    operator_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    result_value = fields.Float(required=True)
    z_score = fields.Float(compute="_compute_qc", store=True)
    analytical_sigma = fields.Float(compute="_compute_qc", store=True)
    prev_z_score = fields.Float(compute="_compute_qc", store=True)
    prev2_z_score = fields.Float(compute="_compute_qc", store=True)
    moving_avg_20 = fields.Float(compute="_compute_qc", store=True)
    moving_sd_20 = fields.Float(compute="_compute_qc", store=True)
    westgard_rules = fields.Char(compute="_compute_qc", store=True)
    westgard_rule_count = fields.Integer(compute="_compute_qc", store=True)
    status = fields.Selection(
        [("pass", "Pass"), ("warning", "Warning"), ("reject", "Reject")],
        compute="_compute_qc",
        store=True,
        tracking=True,
    )
    rule_triggered = fields.Char(compute="_compute_qc", store=True)
    note = fields.Text()

    def _material_rule_codes(self):
        self.ensure_one()
        if self.qc_material_id.rule_ids:
            return set(self.qc_material_id.rule_ids.filtered("active").mapped("code"))
        return set(self.env["lab.qc.rule.library"].search([("active", "=", True)]).mapped("code"))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.qc.run") or "New"
        records = super().create(vals_list)
        records._auto_create_reject_nonconformance()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "status" in vals or "result_value" in vals or "qc_material_id" in vals:
            self._auto_create_reject_nonconformance()
        return res

    @api.depends(
        "result_value",
        "qc_material_id.target_value",
        "qc_material_id.std_dev",
        "qc_material_id.rule_ids",
        "qc_material_id.rule_ids.active",
    )
    def _compute_qc(self):
        for rec in self:
            std_dev = rec.qc_material_id.std_dev or 0.0
            if std_dev <= 0:
                rec.z_score = 0.0
                rec.analytical_sigma = 0.0
                rec.prev_z_score = 0.0
                rec.prev2_z_score = 0.0
                rec.moving_avg_20 = rec.result_value or 0.0
                rec.moving_sd_20 = 0.0
                rec.westgard_rules = "invalid_sd"
                rec.westgard_rule_count = 1
                rec.status = "reject"
                rec.rule_triggered = "invalid_sd"
                continue

            z = (rec.result_value - rec.qc_material_id.target_value) / std_dev
            # Analytical sigma proxy for dashboarding (target/sd).
            rec.analytical_sigma = abs(rec.qc_material_id.target_value or 0.0) / std_dev
            rec.z_score = z
            abs_z = abs(z)

            prev_runs = self.search(
                [
                    ("qc_material_id", "=", rec.qc_material_id.id),
                    ("id", "!=", rec.id),
                    ("run_date", "<=", rec.run_date),
                ],
                order="run_date desc, id desc",
                limit=20,
            )
            prev_z = prev_runs[:1].z_score if prev_runs else 0.0
            prev2_z = prev_runs[1:2].z_score if len(prev_runs) > 1 else 0.0
            rec.prev_z_score = prev_z
            rec.prev2_z_score = prev2_z

            result_values = [rec.result_value] + prev_runs.mapped("result_value")
            if result_values:
                avg = sum(result_values) / len(result_values)
                rec.moving_avg_20 = avg
                rec.moving_sd_20 = (
                    (sum((v - avg) ** 2 for v in result_values) / len(result_values)) ** 0.5
                    if len(result_values) > 1
                    else 0.0
                )
            else:
                rec.moving_avg_20 = 0.0
                rec.moving_sd_20 = 0.0

            reject_rules = []
            warning_rules = []
            enabled_rules = rec._material_rule_codes()

            if "13s" in enabled_rules and abs_z > 3:
                reject_rules.append("13s")
            elif "12s" in enabled_rules and abs_z > 2:
                warning_rules.append("12s")

            if "22s" in enabled_rules and prev_runs and abs(prev_z) > 2 and abs_z > 2 and (prev_z * z) > 0:
                reject_rules.append("22s")

            if "R4s" in enabled_rules and prev_runs and (prev_z * z) < 0 and abs(prev_z - z) > 4:
                reject_rules.append("R4s")

            seq_4 = [z] + prev_runs.mapped("z_score")[:3]
            if (
                "41s" in enabled_rules
                and len(seq_4) == 4
                and all(abs(v) >= 1 for v in seq_4)
                and (all(v > 0 for v in seq_4) or all(v < 0 for v in seq_4))
            ):
                warning_rules.append("41s")

            seq_10 = [z] + prev_runs.mapped("z_score")[:9]
            if "10x" in enabled_rules and len(seq_10) == 10 and (all(v > 0 for v in seq_10) or all(v < 0 for v in seq_10)):
                warning_rules.append("10x")

            all_rules = reject_rules + warning_rules
            rec.westgard_rule_count = len(all_rules)
            rec.westgard_rules = ", ".join(all_rules) if all_rules else "in_control"
            if reject_rules:
                rec.status = "reject"
                rec.rule_triggered = reject_rules[0]
            elif warning_rules:
                rec.status = "warning"
                rec.rule_triggered = warning_rules[0]
            else:
                rec.status = "pass"
                rec.rule_triggered = "in_control"

    @api.constrains("qc_material_id", "run_date")
    def _check_duplicate_timestamp(self):
        for rec in self:
            if not rec.qc_material_id or not rec.run_date:
                continue
            dup = self.search_count(
                [
                    ("id", "!=", rec.id),
                    ("qc_material_id", "=", rec.qc_material_id.id),
                    ("run_date", "=", rec.run_date),
                ]
            )
            if dup:
                raise ValidationError(_("A QC run already exists for this material at the same datetime."))

    def _auto_create_reject_nonconformance(self):
        ncr_obj = self.env["lab.nonconformance"]
        for rec in self:
            if rec.status != "reject":
                continue
            exists = ncr_obj.search(
                [
                    ("qc_run_id", "=", rec.id),
                    ("state", "in", ("draft", "open", "investigation", "capa")),
                ],
                limit=1,
            )
            if exists:
                continue
            title = _("QC Rejected: %s") % rec.service_id.name
            desc = _(
                "QC run %(run)s was rejected by rule %(rule)s (z-score=%(z)s)."
            ) % {"run": rec.name, "rule": rec.rule_triggered or "-", "z": f"{rec.z_score:.2f}"}
            ncr_obj.create(
                {
                    "title": title,
                    "description": desc,
                    "source_type": "qc",
                    "qc_run_id": rec.id,
                    "severity": "major",
                    "owner_id": rec.operator_id.id,
                    "state": "open",
                }
            )

    def action_capture_trend_snapshot(self):
        self.env["lab.qc.daily.snapshot"].action_capture_from_runs(self)
        return True


class LabQcRuleLibrary(models.Model):
    _name = "lab.qc.rule.library"
    _description = "QC Rule Library"
    _order = "code"

    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("13s", "13s"),
            ("12s", "12s"),
            ("22s", "22s"),
            ("R4s", "R4s"),
            ("41s", "41s"),
            ("10x", "10x"),
        ],
        required=True,
    )
    severity = fields.Selection([("warning", "Warning"), ("reject", "Reject")], required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)

    _rule_code_uniq = models.Constraint("unique(code)", "QC rule code must be unique.")


class LabQcDailySnapshot(models.Model):
    _name = "lab.qc.daily.snapshot"
    _description = "QC Daily Snapshot"
    _order = "snapshot_date desc, id desc"

    snapshot_date = fields.Date(required=True, index=True)
    qc_material_id = fields.Many2one("lab.qc.material", required=True, index=True)
    service_id = fields.Many2one("lab.service", required=True, index=True)
    run_count = fields.Integer(default=0)
    pass_count = fields.Integer(default=0)
    warning_count = fields.Integer(default=0)
    reject_count = fields.Integer(default=0)
    reject_rate = fields.Float(compute="_compute_rates", store=True)
    warning_rate = fields.Float(compute="_compute_rates", store=True)
    mean_z = fields.Float(default=0.0)
    max_abs_z = fields.Float(default=0.0)
    sigma_mean = fields.Float(default=0.0)

    @api.depends("run_count", "warning_count", "reject_count")
    def _compute_rates(self):
        for rec in self:
            if not rec.run_count:
                rec.reject_rate = 0.0
                rec.warning_rate = 0.0
                continue
            rec.reject_rate = 100.0 * rec.reject_count / rec.run_count
            rec.warning_rate = 100.0 * rec.warning_count / rec.run_count

    @api.model
    def action_capture_from_runs(self, runs):
        for run in runs:
            day = fields.Date.to_date(run.run_date)
            same_day = self.env["lab.qc.run"].search(
                [
                    ("qc_material_id", "=", run.qc_material_id.id),
                    ("run_date", ">=", fields.Datetime.to_string(day)),
                    ("run_date", "<", fields.Datetime.to_string(fields.Date.add(day, days=1))),
                ]
            )
            z_values = same_day.mapped("z_score")
            vals = {
                "snapshot_date": day,
                "qc_material_id": run.qc_material_id.id,
                "service_id": run.service_id.id,
                "run_count": len(same_day),
                "pass_count": len(same_day.filtered(lambda r: r.status == "pass")),
                "warning_count": len(same_day.filtered(lambda r: r.status == "warning")),
                "reject_count": len(same_day.filtered(lambda r: r.status == "reject")),
                "mean_z": (sum(z_values) / len(z_values)) if z_values else 0.0,
                "max_abs_z": max([abs(z) for z in z_values] or [0.0]),
                "sigma_mean": (sum(same_day.mapped("analytical_sigma")) / len(same_day)) if same_day else 0.0,
            }
            existing = self.search(
                [
                    ("snapshot_date", "=", day),
                    ("qc_material_id", "=", run.qc_material_id.id),
                ],
                limit=1,
            )
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

    @api.model
    def _cron_capture_recent_trends(self):
        start = fields.Datetime.add(fields.Datetime.now(), days=-30)
        runs = self.env["lab.qc.run"].search([("run_date", ">=", start)])
        self.action_capture_from_runs(runs)
