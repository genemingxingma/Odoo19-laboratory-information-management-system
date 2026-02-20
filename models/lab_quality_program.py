from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabQualityProgram(models.Model):
    _name = "lab.quality.program"
    _description = "Laboratory Quality Program"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "year desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    year = fields.Integer(required=True, default=lambda self: fields.Date.today().year, tracking=True)
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, tracking=True)
    objective = fields.Text(required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("closed", "Closed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        required=True,
    )
    line_ids = fields.One2many("lab.quality.program.line", "program_id", string="Program Lines")
    audit_ids = fields.One2many("lab.quality.audit", "program_id", string="Audits", readonly=True)
    training_ids = fields.One2many("lab.quality.training", "program_id", string="Trainings", readonly=True)
    kpi_snapshot_ids = fields.One2many("lab.quality.kpi.snapshot", "program_id", string="KPI Snapshots", readonly=True)

    total_line = fields.Integer(compute="_compute_line_stats", store=True)
    completed_line = fields.Integer(compute="_compute_line_stats", store=True)
    overdue_line = fields.Integer(compute="_compute_line_stats", store=True)
    completion_rate = fields.Float(compute="_compute_line_stats", store=True)

    audit_count = fields.Integer(compute="_compute_counts")
    training_count = fields.Integer(compute="_compute_counts")
    kpi_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids", "line_ids.state", "line_ids.deadline")
    def _compute_line_stats(self):
        today = fields.Date.today()
        for rec in self:
            rec.total_line = len(rec.line_ids)
            rec.completed_line = len(rec.line_ids.filtered(lambda l: l.state == "done"))
            rec.overdue_line = len(
                rec.line_ids.filtered(lambda l: l.state not in ("done", "cancel") and l.deadline and l.deadline < today)
            )
            rec.completion_rate = (100.0 * rec.completed_line / rec.total_line) if rec.total_line else 0.0

    def _compute_counts(self):
        for rec in self:
            rec.audit_count = len(rec.audit_ids)
            rec.training_count = len(rec.training_ids)
            rec.kpi_count = len(rec.kpi_snapshot_ids)

    @api.constrains("year")
    def _check_year(self):
        for rec in self:
            if rec.year < 2000 or rec.year > 2100:
                raise ValidationError(_("Quality Program year must be between 2000 and 2100."))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.quality.program") or "New"
        return super().create(vals_list)

    def action_activate(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.line_ids:
                raise UserError(_("Add at least one program line before activation."))
            rec.state = "active"
            rec.message_post(body=_("Quality program activated."))
        return True

    def action_close(self):
        for rec in self:
            open_lines = rec.line_ids.filtered(lambda l: l.state not in ("done", "cancel"))
            if open_lines:
                raise UserError(_("All program lines must be completed/cancelled before closing."))
            rec.state = "closed"
            rec.message_post(body=_("Quality program closed."))
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        return True

    def action_reset_draft(self):
        self.write({"state": "draft"})
        return True

    def action_view_audits(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_quality_audit").sudo().read()[0]
        action["domain"] = [("program_id", "=", self.id)]
        action["context"] = {"default_program_id": self.id}
        return action

    def action_view_trainings(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_quality_training").sudo().read()[0]
        action["domain"] = [("program_id", "=", self.id)]
        action["context"] = {"default_program_id": self.id}
        return action

    def action_view_kpi(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_quality_kpi_snapshot").sudo().read()[0]
        action["domain"] = [("program_id", "=", self.id)]
        action["context"] = {"default_program_id": self.id}
        return action

    def action_generate_default_lines(self):
        templates = [
            ("Internal audit for all departments", "audit"),
            ("Proficiency test participation", "proficiency"),
            ("Instrument calibration traceability check", "calibration"),
            ("Reagent lot expiry & FEFO review", "inventory"),
            ("Manual review backlog review", "manual_review"),
            ("Staff competency reassessment", "competency"),
            ("Customer complaint trend analysis", "complaint"),
            ("CAPA effectiveness verification", "capa"),
        ]
        for rec in self:
            exists = set(rec.line_ids.mapped("code"))
            lines = []
            for idx, (title, code) in enumerate(templates, start=1):
                if code in exists:
                    continue
                lines.append(
                    (
                        0,
                        0,
                        {
                            "name": title,
                            "code": code,
                            "sequence": idx * 10,
                            "owner_id": rec.owner_id.id,
                            "deadline": date(rec.year, min(idx, 12), 28),
                        },
                    )
                )
            if lines:
                rec.write({"line_ids": lines})
        return True


class LabQualityProgramLine(models.Model):
    _name = "lab.quality.program.line"
    _description = "Quality Program Line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    program_id = fields.Many2one("lab.quality.program", required=True, ondelete="cascade", index=True)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    owner_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("general", "General"),
        ],
        default="general",
        required=True,
    )
    category = fields.Selection(
        [
            ("audit", "Audit"),
            ("proficiency", "Proficiency"),
            ("competency", "Competency"),
            ("inventory", "Inventory"),
            ("calibration", "Calibration"),
            ("manual_review", "Manual Review"),
            ("complaint", "Complaint"),
            ("capa", "CAPA"),
            ("other", "Other"),
        ],
        default="other",
    )
    deadline = fields.Date()
    completed_date = fields.Date(readonly=True)
    score = fields.Float()
    target = fields.Float(default=100.0)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
    )
    result_note = fields.Text()

    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=False)
    is_passed = fields.Boolean(compute="_compute_is_passed", store=True)

    @api.depends("deadline", "state")
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = bool(rec.deadline and rec.deadline < today and rec.state not in ("done", "cancel"))

    @api.depends("score", "target", "state")
    def _compute_is_passed(self):
        for rec in self:
            rec.is_passed = rec.state == "done" and rec.score >= rec.target

    @api.constrains("score", "target")
    def _check_score_range(self):
        for rec in self:
            if rec.score < 0 or rec.target < 0:
                raise ValidationError(_("Score and target must be non-negative."))

    def action_start(self):
        self.write({"state": "in_progress"})
        return True

    def action_done(self):
        for rec in self:
            rec.write({"state": "done", "completed_date": fields.Date.today()})
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        return True

    def action_reset(self):
        self.write({"state": "draft", "completed_date": False})
        return True


class LabQualityAudit(models.Model):
    _name = "lab.quality.audit"
    _description = "Laboratory Internal Audit"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "audit_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    program_id = fields.Many2one("lab.quality.program", required=True, ondelete="restrict", index=True)
    audit_date = fields.Date(default=fields.Date.today, required=True, tracking=True)
    scope = fields.Text(required=True)
    lead_auditor_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, tracking=True)
    auditor_ids = fields.Many2many("res.users", string="Auditors")
    auditee_ids = fields.Many2many("res.partner", string="Auditees")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("closed", "Closed"),
        ],
        default="draft",
        tracking=True,
    )
    finding_ids = fields.One2many("lab.quality.audit.finding", "audit_id", string="Findings")
    summary = fields.Text()

    major_count = fields.Integer(compute="_compute_finding_stats")
    minor_count = fields.Integer(compute="_compute_finding_stats")
    obs_count = fields.Integer(compute="_compute_finding_stats")
    open_count = fields.Integer(compute="_compute_finding_stats")

    @api.depends("finding_ids.severity", "finding_ids.state")
    def _compute_finding_stats(self):
        for rec in self:
            rec.major_count = len(rec.finding_ids.filtered(lambda f: f.severity == "major"))
            rec.minor_count = len(rec.finding_ids.filtered(lambda f: f.severity == "minor"))
            rec.obs_count = len(rec.finding_ids.filtered(lambda f: f.severity == "observation"))
            rec.open_count = len(rec.finding_ids.filtered(lambda f: f.state != "closed"))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.quality.audit") or "New"
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "running"})
        return True

    def action_complete(self):
        for rec in self:
            if not rec.finding_ids:
                raise UserError(_("Add at least one finding before completion."))
            rec.state = "completed"
        return True

    def action_close(self):
        for rec in self:
            open_findings = rec.finding_ids.filtered(lambda f: f.state != "closed")
            if open_findings:
                raise UserError(_("All findings must be closed before closing audit."))
            rec.state = "closed"
        return True

    def action_reset(self):
        self.write({"state": "draft"})
        return True


class LabQualityAuditFinding(models.Model):
    _name = "lab.quality.audit.finding"
    _description = "Audit Finding"
    _order = "id desc"

    audit_id = fields.Many2one("lab.quality.audit", required=True, ondelete="cascade", index=True)
    title = fields.Char(required=True)
    description = fields.Text(required=True)
    severity = fields.Selection(
        [
            ("major", "Major"),
            ("minor", "Minor"),
            ("observation", "Observation"),
        ],
        default="minor",
        required=True,
    )
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    target_date = fields.Date()
    close_date = fields.Date(readonly=True)
    corrective_action = fields.Text()
    effectiveness_note = fields.Text()
    state = fields.Selection(
        [
            ("open", "Open"),
            ("implemented", "Implemented"),
            ("verified", "Verified"),
            ("closed", "Closed"),
        ],
        default="open",
    )

    is_overdue = fields.Boolean(compute="_compute_overdue")

    def _compute_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = bool(rec.target_date and rec.target_date < today and rec.state != "closed")

    def action_implement(self):
        self.write({"state": "implemented"})
        return True

    def action_verify(self):
        self.write({"state": "verified"})
        return True

    def action_close(self):
        for rec in self:
            rec.write({"state": "closed", "close_date": fields.Date.today()})
        return True

    def action_reopen(self):
        self.write({"state": "open", "close_date": False})
        return True


class LabQualityTraining(models.Model):
    _name = "lab.quality.training"
    _description = "Quality Training Session"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "training_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    program_id = fields.Many2one("lab.quality.program", required=True, ondelete="restrict", index=True)
    topic = fields.Char(required=True)
    training_date = fields.Date(default=fields.Date.today, required=True)
    trainer_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    duration_hour = fields.Float(default=1.0)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
    )
    attendee_ids = fields.One2many("lab.quality.training.attendee", "training_id", string="Attendees")
    note = fields.Text()

    attendee_count = fields.Integer(compute="_compute_attendee")
    pass_count = fields.Integer(compute="_compute_attendee")

    @api.depends("attendee_ids.passed")
    def _compute_attendee(self):
        for rec in self:
            rec.attendee_count = len(rec.attendee_ids)
            rec.pass_count = len(rec.attendee_ids.filtered(lambda a: a.passed))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.quality.training") or "New"
        return super().create(vals_list)

    def action_schedule(self):
        self.write({"state": "scheduled"})
        return True

    def action_done(self):
        self.write({"state": "done"})
        return True

    def action_cancel(self):
        self.write({"state": "cancel"})
        return True

    def action_reset(self):
        self.write({"state": "draft"})
        return True


class LabQualityTrainingAttendee(models.Model):
    _name = "lab.quality.training.attendee"
    _description = "Training Attendee"
    _order = "id"

    training_id = fields.Many2one("lab.quality.training", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True)
    attended = fields.Boolean(default=False)
    score = fields.Float(default=0.0)
    passed = fields.Boolean(compute="_compute_pass", store=True)
    comment = fields.Text()

    @api.depends("attended", "score")
    def _compute_pass(self):
        for rec in self:
            rec.passed = bool(rec.attended and rec.score >= 60.0)


class LabQualityKpiSnapshot(models.Model):
    _name = "lab.quality.kpi.snapshot"
    _description = "Quality KPI Snapshot"
    _order = "snapshot_date desc, id desc"

    program_id = fields.Many2one("lab.quality.program", required=True, ondelete="cascade", index=True)
    snapshot_date = fields.Date(default=fields.Date.today, required=True, index=True)
    total_samples = fields.Integer(default=0)
    reported_samples = fields.Integer(default=0)
    overdue_samples = fields.Integer(default=0)
    manual_review_queue = fields.Integer(default=0)
    critical_results = fields.Integer(default=0)
    ncr_open = fields.Integer(default=0)
    dispatch_unacked = fields.Integer(default=0)

    on_time_rate = fields.Float(compute="_compute_rates", store=True)
    overdue_rate = fields.Float(compute="_compute_rates", store=True)

    @api.depends("total_samples", "reported_samples", "overdue_samples")
    def _compute_rates(self):
        for rec in self:
            rec.on_time_rate = (100.0 * rec.reported_samples / rec.total_samples) if rec.total_samples else 0.0
            rec.overdue_rate = (100.0 * rec.overdue_samples / rec.total_samples) if rec.total_samples else 0.0

    @api.model
    def action_capture_kpi(self):
        sample_obj = self.env["lab.sample"]
        analysis_obj = self.env["lab.sample.analysis"]
        ncr_obj = self.env["lab.nonconformance"]
        dispatch_obj = self.env["lab.report.dispatch"]

        programs = self.env["lab.quality.program"].search([("state", "=", "active")])
        if not programs:
            return False

        for program in programs:
            total_samples = sample_obj.search_count([])
            reported_samples = sample_obj.search_count([("state", "=", "reported")])
            overdue_samples = sample_obj.search_count([("is_overdue", "=", True)])
            manual_review_queue = analysis_obj.search_count(
                [
                    ("needs_manual_review", "=", True),
                    ("state", "in", ("assigned", "done")),
                ]
            )
            critical_results = analysis_obj.search_count(
                [
                    ("is_critical", "=", True),
                    ("state", "in", ("done", "verified")),
                ]
            )
            ncr_open = ncr_obj.search_count([("state", "not in", ("closed", "cancel"))])
            dispatch_unacked = dispatch_obj.search_count([("state", "in", ("sent", "viewed", "downloaded"))])

            self.create(
                {
                    "program_id": program.id,
                    "snapshot_date": fields.Date.today(),
                    "total_samples": total_samples,
                    "reported_samples": reported_samples,
                    "overdue_samples": overdue_samples,
                    "manual_review_queue": manual_review_queue,
                    "critical_results": critical_results,
                    "ncr_open": ncr_open,
                    "dispatch_unacked": dispatch_unacked,
                }
            )
        return True

    @api.model
    def _cron_capture_kpi(self):
        return self.action_capture_kpi()


class LabQualityProgramReminderMixin(models.AbstractModel):
    _name = "lab.quality.program.reminder.mixin"
    _description = "Quality Program Reminder Mixin"

    @api.model
    def _cron_notify_quality_program_overdue(self):
        line_obj = self.env["lab.quality.program.line"]
        today = fields.Date.today()
        lines = line_obj.search(
            [
                ("state", "in", ("draft", "in_progress")),
                ("deadline", "!=", False),
                ("deadline", "<", today),
                ("program_id.state", "=", "active"),
            ],
            limit=200,
        )
        if not lines:
            return

        todo = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("lab.quality.program.line")
        for line in lines:
            user = line.owner_id or self.env.user
            summary = "Quality program overdue"
            exists = self.env["mail.activity"].search_count(
                [
                    ("res_model_id", "=", model_id),
                    ("res_id", "=", line.id),
                    ("user_id", "=", user.id),
                    ("summary", "=", summary),
                ]
            )
            if exists:
                continue
            note = _("Quality task %s is overdue since %s.") % (line.name, line.deadline)
            self.env["mail.activity"].create(
                {
                    "activity_type_id": todo.id,
                    "user_id": user.id,
                    "res_model_id": model_id,
                    "res_id": line.id,
                    "summary": summary,
                    "note": note,
                }
            )
