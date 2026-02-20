from datetime import datetime, time, timedelta
from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabSample(models.Model):
    _name = "lab.sample"
    _description = "Laboratory Sample (Accession)"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]
    _order = "id desc"

    name = fields.Char(string="Accession No.", default="New", readonly=True, copy=False, tracking=True)
    accession_barcode = fields.Char(string="Accession Barcode", copy=False, tracking=True)
    patient_id = fields.Many2one("res.partner", required=True, tracking=True)
    client_id = fields.Many2one("res.partner", string="Client/Institution", tracking=True)
    request_id = fields.Many2one("lab.test.request", string="Test Request", copy=False, readonly=True, tracking=True)
    parent_sample_id = fields.Many2one("lab.sample", string="Parent Sample", copy=False, readonly=True)
    aliquot_ids = fields.One2many("lab.sample", "parent_sample_id", string="Aliquots", readonly=True)
    aliquot_count = fields.Integer(compute="_compute_aliquot_count")
    physician_name = fields.Char()
    profile_id = fields.Many2one("lab.profile", string="Profile")
    report_template_id = fields.Many2one(
        "lab.report.template",
        string="Report Template",
        default=lambda self: self.env.ref("laboratory_management.report_template_classic", raise_if_not_found=False),
    )
    current_custodian_id = fields.Many2one("res.users", string="Current Custodian", tracking=True)
    custody_location = fields.Char(string="Current Location")
    collection_date = fields.Datetime(default=fields.Datetime.now)
    received_date = fields.Datetime(readonly=True)
    report_date = fields.Datetime(readonly=True)
    expected_report_date = fields.Datetime(
        string="Expected Report Date",
        compute="_compute_expected_report_date",
        store=True,
    )
    verified_by_id = fields.Many2one("res.users", string="Verified By", readonly=True)
    verified_date = fields.Datetime(readonly=True)
    report_revision = fields.Integer(default=1, readonly=True, tracking=True)
    is_amended = fields.Boolean(default=False, readonly=True, tracking=True)
    amendment_note = fields.Text(string="Amendment Note")
    priority = fields.Selection(
        [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        default="routine",
        required=True,
        tracking=True,
    )
    note = fields.Text()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("received", "Received"),
            ("in_progress", "In Progress"),
            ("to_verify", "To Verify"),
            ("verified", "Verified"),
            ("reported", "Reported"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        tracking=True,
    )

    analysis_ids = fields.One2many("lab.sample.analysis", "sample_id", string="Analyses")
    amendment_ids = fields.One2many("lab.sample.amendment", "sample_id", string="Amendments", readonly=True)
    timeline_ids = fields.One2many("lab.sample.timeline", "sample_id", string="Timeline", readonly=True)
    signoff_ids = fields.One2many("lab.sample.signoff", "sample_id", string="Sign-offs", readonly=True)
    custody_ids = fields.One2many("lab.sample.custody", "sample_id", string="Custody Trail", readonly=True)
    nonconformance_count = fields.Integer(compute="_compute_nonconformance_count")
    total_analysis = fields.Integer(compute="_compute_analysis_stats", store=True)
    done_analysis = fields.Integer(compute="_compute_analysis_stats", store=True)
    verified_analysis = fields.Integer(compute="_compute_analysis_stats", store=True)
    is_overdue = fields.Boolean(compute="_compute_is_overdue", search="_search_is_overdue", store=False)

    @api.depends("analysis_ids.state")
    def _compute_analysis_stats(self):
        for rec in self:
            states = rec.analysis_ids.mapped("state")
            rec.total_analysis = len(states)
            rec.done_analysis = len([s for s in states if s in ("done", "verified")])
            rec.verified_analysis = len([s for s in states if s == "verified"])

    def _compute_aliquot_count(self):
        for rec in self:
            rec.aliquot_count = len(rec.aliquot_ids)

    def _compute_nonconformance_count(self):
        ncr_obj = self.env["lab.nonconformance"]
        for rec in self:
            rec.nonconformance_count = ncr_obj.search_count([("sample_id", "=", rec.id)])

    @api.depends("analysis_ids.service_id.turnaround_hours", "received_date", "collection_date")
    def _compute_expected_report_date(self):
        for rec in self:
            base = rec.received_date or rec.collection_date
            if not base:
                rec.expected_report_date = False
                continue
            tat_hours = 0
            if rec.analysis_ids:
                tat_hours = max(rec.analysis_ids.mapped("service_id.turnaround_hours") or [0])
            rec.expected_report_date = fields.Datetime.add(base, hours=tat_hours)

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(
                rec.expected_report_date
                and rec.state not in ("reported", "cancel")
                and rec.expected_report_date < now
            )

    def _search_is_overdue(self, operator, value):
        now = fields.Datetime.now()
        overdue_domain = [
            ("expected_report_date", "!=", False),
            ("expected_report_date", "<", now),
            ("state", "not in", ("reported", "cancel")),
        ]
        not_overdue_domain = [
            "|",
            ("expected_report_date", "=", False),
            "|",
            ("expected_report_date", ">=", now),
            ("state", "in", ("reported", "cancel")),
        ]
        if operator in ("=", "=="):
            return overdue_domain if value else not_overdue_domain
        if operator == "!=":
            return not_overdue_domain if value else overdue_domain
        return overdue_domain

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.sample") or "New"
            if not vals.get("accession_barcode"):
                vals["accession_barcode"] = vals.get("name")
        records = super().create(vals_list)
        for rec in records:
            if not rec.current_custodian_id:
                rec.current_custodian_id = rec.create_uid.id
            if not rec.custody_ids:
                rec._create_custody_event("register", rec.current_custodian_id, rec.custody_location, _("Sample registered"))
            if rec.profile_id and not rec.analysis_ids:
                rec.action_add_profile_services()
        return records

    def action_add_profile_services(self):
        for rec in self:
            if not rec.profile_id:
                raise UserError(_("Please select an analysis profile first."))
            existing_service_ids = rec.analysis_ids.mapped("service_id").ids
            new_lines = []
            for line in rec.profile_id.line_ids:
                if line.service_id.id not in existing_service_ids:
                    new_lines.append(
                        (0, 0, {"service_id": line.service_id.id, "state": "pending"})
                    )
            if not new_lines:
                raise UserError(_("All profile services are already added."))
            rec.write({"analysis_ids": new_lines})

    def action_receive(self):
        for rec in self:
            if not rec.analysis_ids:
                raise UserError(_("Add at least one analysis before receiving sample."))
            rec.current_custodian_id = self.env.user.id
            rec.write({"state": "received", "received_date": fields.Datetime.now()})
            rec._log_timeline("received", _("Sample received"))
            rec._create_custody_event("receive", self.env.user, rec.custody_location, _("Sample received"))
            rec._create_signoff("receive", _("Sample received at accessioning desk"))

    def action_start(self):
        for rec in self:
            if rec.state not in ("received", "draft"):
                continue
            rec.analysis_ids.filtered(lambda x: x.state == "pending").write({"state": "assigned"})
            rec.state = "in_progress"
            rec._log_timeline("in_progress", _("Analyses started"))
            rec._create_signoff("start", _("Analyses started"))

    def action_mark_to_verify(self):
        for rec in self:
            active_analyses = rec.analysis_ids.filtered(lambda x: x.state != "rejected")
            if not active_analyses:
                raise UserError(_("No active analyses available for verification."))
            if active_analyses.filtered(lambda x: x.state not in ("done", "verified")):
                raise UserError(_("All analyses must be done before moving to verification."))
            rec.state = "to_verify"
            rec._log_timeline("to_verify", _("All analyses completed, moved to verification queue"))

    def action_verify(self):
        for rec in self:
            unverified = rec.analysis_ids.filtered(lambda x: x.state != "verified")
            if unverified:
                unverified.action_verify_result()
            rec.write(
                {
                    "state": "verified",
                    "verified_by_id": self.env.user.id,
                    "verified_date": fields.Datetime.now(),
                }
            )
            rec._log_timeline("verified", _("Results verified"))
            rec._create_signoff("verify", _("Results verified"))

    def action_release_report(self):
        for rec in self:
            if rec.state != "verified":
                raise UserError(_("Only verified samples can be released."))
            rec.write({"state": "reported", "report_date": fields.Datetime.now()})
            rec._log_timeline("reported", _("Report released"))
            rec._create_custody_event("release", False, rec.custody_location, _("Report released to requester"))
            rec._create_signoff("release", _("Report released"))

    def action_print_report(self):
        self.ensure_one()
        code = self.report_template_id.code if self.report_template_id else "classic"
        xmlid_map = {
            "classic": "laboratory_management.action_report_lab_sample_classic",
            "clinical": "laboratory_management.action_report_lab_sample_clinical",
            "compact": "laboratory_management.action_report_lab_sample_compact",
        }
        action = self.env.ref(xmlid_map.get(code, xmlid_map["classic"]))
        return action.report_action(self)

    def get_report_action_xmlid(self):
        self.ensure_one()
        code = self.report_template_id.code if self.report_template_id else "classic"
        xmlid_map = {
            "classic": "laboratory_management.action_report_lab_sample_classic",
            "clinical": "laboratory_management.action_report_lab_sample_clinical",
            "compact": "laboratory_management.action_report_lab_sample_compact",
        }
        return xmlid_map.get(code, xmlid_map["classic"])

    def action_cancel(self):
        self.write({"state": "cancel"})
        for rec in self:
            rec._log_timeline("cancel", _("Sample cancelled"))

    def action_reset_draft(self):
        self.write({"state": "draft"})
        for rec in self:
            rec._log_timeline("draft", _("Reset to draft"))

    @api.model
    def _cron_notify_overdue_samples(self):
        overdue_samples = self.search(
            [
                ("expected_report_date", "!=", False),
                ("expected_report_date", "<", fields.Datetime.now()),
                ("state", "not in", ("reported", "cancel")),
            ]
        )
        if not overdue_samples:
            return

        todo = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("lab.sample")
        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        users = reviewer_group.user_ids if (reviewer_group and reviewer_group.user_ids) else self.env.user

        for sample in overdue_samples:
            summary = "Overdue sample follow-up"
            note = (
                "Sample %s for %s is overdue. Expected report date: %s."
                % (sample.name, sample.patient_id.name, sample.expected_report_date)
            )
            for user in users:
                exists = self.env["mail.activity"].search_count(
                    [
                        ("res_model_id", "=", model_id),
                        ("res_id", "=", sample.id),
                        ("user_id", "=", user.id),
                        ("summary", "=", summary),
                    ]
                )
                if exists:
                    continue
                self.env["mail.activity"].create(
                    {
                        "activity_type_id": todo.id,
                        "user_id": user.id,
                        "res_model_id": model_id,
                        "res_id": sample.id,
                        "summary": summary,
                        "note": note,
                    }
                )

    def action_view_aliquots(self):
        self.ensure_one()
        return {
            "name": _("Aliquots"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("parent_sample_id", "=", self.id)],
            "context": {"default_parent_sample_id": self.id},
        }

    def action_view_nonconformances(self):
        self.ensure_one()
        return {
            "name": _("Nonconformances"),
            "type": "ir.actions.act_window",
            "res_model": "lab.nonconformance",
            "view_mode": "list,form",
            "domain": [("sample_id", "=", self.id)],
            "context": {
                "default_sample_id": self.id,
                "default_source_type": "sample",
            },
        }

    def action_create_aliquot(self):
        self.ensure_one()
        aliquot = self.copy(
            {
                "parent_sample_id": self.id,
                "state": "draft",
                "received_date": False,
                "verified_by_id": False,
                "verified_date": False,
                "report_date": False,
                "report_revision": 1,
                "is_amended": False,
                "amendment_note": False,
                "current_custodian_id": self.current_custodian_id.id,
                "custody_location": self.custody_location,
            }
        )
        aliquot.analysis_ids.unlink()
        new_lines = []
        for line in self.analysis_ids:
            new_lines.append(
                (
                    0,
                    0,
                    {
                        "service_id": line.service_id.id,
                        "state": "pending",
                        "analyst_id": line.analyst_id.id,
                    },
                )
            )
        if new_lines:
            aliquot.write({"analysis_ids": new_lines})
        aliquot._log_timeline("draft", _("Aliquot created from %s") % self.name)
        aliquot._create_custody_event(
            "aliquot",
            self.current_custodian_id,
            self.custody_location,
            _("Aliquot created from %s") % self.name,
        )
        self._log_timeline("aliquot", _("Created aliquot %s") % aliquot.name)
        self._create_signoff("aliquot", _("Created aliquot %s") % aliquot.name)
        return {
            "type": "ir.actions.act_window",
            "res_model": "lab.sample",
            "res_id": aliquot.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_amend_report(self):
        for rec in self:
            if rec.state != "reported":
                raise UserError(_("Only released reports can be amended."))
            note = rec.amendment_note or _("Report amended without detailed note.")
            next_revision = rec.report_revision + 1
            self.env["lab.sample.amendment"].create(
                {
                    "sample_id": rec.id,
                    "revision": next_revision,
                    "note": note,
                    "amended_by_id": self.env.user.id,
                    "amended_date": fields.Datetime.now(),
                }
            )
            rec.write(
                {
                    "report_revision": next_revision,
                    "is_amended": True,
                    "state": "verified",
                }
            )
            rec._log_timeline("amendment", _("Report amended to revision R%s") % next_revision)
            rec._create_signoff("amend", _("Amended report to revision R%s") % next_revision)

    def _log_timeline(self, event_type, note):
        self.ensure_one()
        self.env["lab.sample.timeline"].create(
            {
                "sample_id": self.id,
                "event_type": event_type,
                "event_time": fields.Datetime.now(),
                "user_id": self.env.user.id,
                "note": note,
            }
        )

    def _create_signoff(self, action_type, note):
        self.ensure_one()
        self.env["lab.sample.signoff"].create(
            {
                "sample_id": self.id,
                "action_type": action_type,
                "signed_at": fields.Datetime.now(),
                "signed_by_id": self.env.user.id,
                "signature_ref": str(uuid4()),
                "note": note,
            }
        )

    def action_open_transfer_custody_wizard(self):
        self.ensure_one()
        return {
            "name": _("Transfer Custody"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sample.transfer.custody.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_sample_id": self.id,
                "default_from_user_id": self.current_custodian_id.id or self.env.user.id,
                "default_location": self.custody_location,
            },
        }

    def _transfer_custody(self, to_user, location, note):
        self.ensure_one()
        if not to_user:
            raise UserError(_("Please select the assignee user."))
        self.write(
            {
                "current_custodian_id": to_user.id,
                "custody_location": location,
            }
        )
        transfer_note = note or _("Custody transferred")
        self._create_custody_event("transfer", to_user, location, transfer_note)

    def _create_custody_event(self, event_type, to_user, location, note):
        self.ensure_one()
        if event_type == "register":
            from_user = False
        else:
            last_event = self.custody_ids[:1]
            from_user = last_event.to_user_id if last_event else self.current_custodian_id
        self.env["lab.sample.custody"].create(
            {
                "sample_id": self.id,
                "event_type": event_type,
                "from_user_id": from_user.id if from_user else False,
                "to_user_id": to_user.id if to_user else False,
                "event_time": fields.Datetime.now(),
                "location": location or False,
                "note": note,
            }
        )

    def _auto_create_nonconformance(self, title, description, severity="major", analysis=False):
        self.ensure_one()
        ncr_obj = self.env["lab.nonconformance"]
        domain = [
            ("sample_id", "=", self.id),
            ("title", "=", title),
            ("state", "in", ("draft", "open", "investigation", "capa")),
        ]
        if analysis:
            domain.append(("analysis_id", "=", analysis.id))
        existing = ncr_obj.search(domain, limit=1)
        if existing:
            return existing
        return ncr_obj.create(
            {
                "title": title,
                "description": description,
                "sample_id": self.id,
                "analysis_id": analysis.id if analysis else False,
                "source_type": "analysis" if analysis else "sample",
                "severity": severity,
                "owner_id": self.env.user.id,
                "state": "open",
            }
        )


class LabSampleAnalysis(models.Model):
    _name = "lab.sample.analysis"
    _description = "Sample Analysis"
    _order = "id"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    retest_of_id = fields.Many2one("lab.sample.analysis", string="Retest Of", copy=False)
    retest_ids = fields.One2many("lab.sample.analysis", "retest_of_id", string="Retests", readonly=True)
    is_retest = fields.Boolean(compute="_compute_is_retest")
    service_id = fields.Many2one("lab.service", required=True)
    reagent_lot_id = fields.Many2one("lab.reagent.lot", string="Reagent Lot")
    worksheet_id = fields.Many2one("lab.worksheet")
    analyst_id = fields.Many2one("res.users", string="Analyst")
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("assigned", "Assigned"),
            ("done", "Done"),
            ("verified", "Verified"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
    )
    result_value = fields.Char()
    result_note = fields.Char()
    auto_verified = fields.Boolean(default=False, readonly=True)
    delta_previous_value = fields.Float(readonly=True)
    delta_check_value = fields.Float(readonly=True)
    delta_check_status = fields.Selection(
        [("na", "N/A"), ("pass", "Pass"), ("fail", "Fail")],
        default="na",
        readonly=True,
    )
    manual_review_reason_code = fields.Selection(
        [
            ("auto_disabled", "Auto-Verification Disabled"),
            ("critical", "Critical Result"),
            ("out_of_range", "Out of Reference Range"),
            ("qc_not_passed", "QC Not Passed"),
            ("delta_fail", "Delta Check Failed"),
        ],
        readonly=True,
    )
    manual_review_reason_note = fields.Text(readonly=True)
    manual_review_recommendation = fields.Text(readonly=True)
    needs_manual_review = fields.Boolean(default=False, readonly=True)
    review_due_date = fields.Datetime(readonly=True)
    review_overdue = fields.Boolean(compute="_compute_review_overdue", search="_search_review_overdue")
    review_assigned_user_id = fields.Many2one("res.users", string="Review Assignee", readonly=True)
    review_assigned_date = fields.Datetime(readonly=True)
    manual_reviewed_by_id = fields.Many2one("res.users", readonly=True)
    manual_reviewed_date = fields.Datetime(readonly=True)
    result_flag = fields.Selection(
        [("normal", "Normal"), ("high", "High"), ("low", "Low")],
        compute="_compute_result_flag",
        store=True,
    )
    is_out_of_range = fields.Boolean(compute="_compute_result_flag", store=True)

    unit = fields.Char(related="service_id.unit", store=True)
    ref_min = fields.Float(related="service_id.ref_min", store=True)
    ref_max = fields.Float(related="service_id.ref_max", store=True)
    critical_min = fields.Float(related="service_id.critical_min", store=True)
    critical_max = fields.Float(related="service_id.critical_max", store=True)
    department = fields.Selection(related="service_id.department", store=True)
    sample_type = fields.Selection(related="service_id.sample_type", store=True)
    is_critical = fields.Boolean(compute="_compute_result_flag", store=True)

    def _compute_is_retest(self):
        for rec in self:
            rec.is_retest = bool(rec.retest_of_id)

    def _compute_review_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.review_overdue = bool(
                rec.needs_manual_review
                and rec.review_due_date
                and rec.state in ("assigned", "done")
                and rec.review_due_date < now
            )

    def _search_review_overdue(self, operator, value):
        now = fields.Datetime.now()
        overdue_domain = [
            ("needs_manual_review", "=", True),
            ("review_due_date", "!=", False),
            ("review_due_date", "<", now),
            ("state", "in", ("assigned", "done")),
        ]
        not_overdue_domain = [
            "|",
            ("needs_manual_review", "=", False),
            "|",
            ("review_due_date", "=", False),
            "|",
            ("review_due_date", ">=", now),
            ("state", "not in", ("assigned", "done")),
        ]
        if operator in ("=", "=="):
            return overdue_domain if value else not_overdue_domain
        if operator == "!=":
            return not_overdue_domain if value else overdue_domain
        return overdue_domain

    @api.depends("result_value", "service_id.result_type", "ref_min", "ref_max")
    def _compute_result_flag(self):
        for rec in self:
            flag = "normal"
            out_of_range = False
            is_critical = False
            if rec.service_id.result_type == "numeric" and rec.result_value not in (False, ""):
                try:
                    num = float(rec.result_value)
                    if num < rec.ref_min:
                        flag = "low"
                        out_of_range = True
                    elif num > rec.ref_max:
                        flag = "high"
                        out_of_range = True
                except (TypeError, ValueError):
                    flag = "normal"
                    out_of_range = False
                if rec.critical_min not in (False, None) and num < rec.critical_min:
                    is_critical = True
                if rec.critical_max not in (False, None) and num > rec.critical_max:
                    is_critical = True
            rec.result_flag = flag
            rec.is_out_of_range = out_of_range
            rec.is_critical = is_critical

    @api.constrains("result_value", "service_id")
    def _check_numeric_result(self):
        for rec in self:
            if rec.service_id.result_type == "numeric" and rec.result_value not in (False, ""):
                try:
                    float(rec.result_value)
                except ValueError as exc:
                    raise ValidationError(_("Numeric result expected for service %s") % rec.service_id.name) from exc

    def action_mark_done(self):
        for rec in self:
            if rec.result_value in (False, ""):
                raise UserError(_("Please input result value for %s") % rec.service_id.name)
            qc_run = False
            if rec.service_id.require_reagent_lot and not rec.reagent_lot_id:
                raise UserError(
                    _("Service %(service)s requires reagent lot before marking done.")
                    % {"service": rec.service_id.name}
                )
            if rec.reagent_lot_id and rec.reagent_lot_id.is_expired:
                raise UserError(
                    _("Reagent lot %(lot)s is expired and cannot be used.")
                    % {"lot": rec.reagent_lot_id.display_name}
                )
            if rec.service_id.require_qc:
                qc_run = self.env["lab.qc.run"].search(
                    [("service_id", "=", rec.service_id.id)],
                    order="run_date desc, id desc",
                    limit=1,
                )
                if not qc_run:
                    raise UserError(
                        _("QC is required for %(service)s, but no QC run exists.")
                        % {"service": rec.service_id.name}
                    )
                if qc_run.status == "reject":
                    raise UserError(
                        _(
                            "Latest QC for %(service)s is rejected (rule: %(rule)s). "
                            "Please run QC again before releasing results."
                        )
                        % {"service": rec.service_id.name, "rule": qc_run.rule_triggered or "-"}
                    )

            auto_verifiable = rec._can_auto_verify(qc_run=qc_run)
            rec.write(
                {
                    "state": "verified" if auto_verifiable else "done",
                    "auto_verified": auto_verifiable,
                    "manual_reviewed_by_id": False,
                    "manual_reviewed_date": False,
                }
            )

            if rec.is_critical:
                rec._create_critical_alert()

            if auto_verifiable:
                rec.sample_id.message_post(
                    body=_("Result auto-verified for %(service)s.") % {"service": rec.service_id.name},
                    subtype_xmlid="mail.mt_note",
                )
            elif rec.needs_manual_review:
                rec.sample_id.message_post(
                    body=_("Manual review required for %(service)s due to delta check failure.")
                    % {"service": rec.service_id.name},
                    subtype_xmlid="mail.mt_note",
                )
        self._sync_sample_states()

    def action_verify_result(self):
        self.write(
            {
                "state": "verified",
                "auto_verified": False,
                "needs_manual_review": False,
                "manual_reviewed_by_id": self.env.user.id,
                "manual_reviewed_date": fields.Datetime.now(),
                "review_due_date": False,
                "review_assigned_user_id": False,
                "review_assigned_date": False,
            }
        )
        self._sync_sample_states(set_verified_by_user=True)

    def action_reject_result(self):
        self.write(
            {
                "state": "rejected",
                "auto_verified": False,
                "needs_manual_review": False,
                "manual_reviewed_by_id": self.env.user.id,
                "manual_reviewed_date": fields.Datetime.now(),
                "review_due_date": False,
                "review_assigned_user_id": False,
                "review_assigned_date": False,
            }
        )
        self._sync_sample_states()

    def action_request_retest(self):
        for rec in self:
            retest = self.create(
                {
                    "sample_id": rec.sample_id.id,
                    "service_id": rec.service_id.id,
                    "worksheet_id": False,
                    "analyst_id": rec.analyst_id.id,
                    "state": "pending",
                    "retest_of_id": rec.id,
                }
            )
            rec.state = "rejected"
            rec.auto_verified = False
            rec.needs_manual_review = False
            rec.review_due_date = False
            rec.review_assigned_user_id = False
            rec.review_assigned_date = False
            rec.sample_id.message_post(
                body=_("Retest requested for %(service)s (new analysis line #%(line)s).")
                % {"service": rec.service_id.name, "line": retest.id},
                subtype_xmlid="mail.mt_note",
            )
            rec.sample_id._log_timeline("retest", _("Retest requested for %s") % rec.service_id.name)
            rec.sample_id._create_signoff("retest", _("Retest requested for %s") % rec.service_id.name)
        self._sync_sample_states()

    def _sync_sample_states(self, set_verified_by_user=False):
        """Keep sample workflow aligned with analysis-level progress."""
        for sample in self.mapped("sample_id"):
            if sample.state in ("cancel", "reported"):
                continue
            active_lines = sample.analysis_ids.filtered(lambda x: x.state != "rejected")
            states = active_lines.mapped("state")
            if states and all(s == "verified" for s in states):
                vals = {"state": "verified"}
                if set_verified_by_user:
                    vals.update(
                        {
                            "verified_by_id": self.env.user.id,
                            "verified_date": fields.Datetime.now(),
                        }
                    )
                sample.write(vals)
                continue
            if states and all(s in ("done", "verified") for s in states):
                if sample.state in ("draft", "received", "in_progress"):
                    sample.state = "to_verify"
                continue
            if any(s in ("assigned", "done", "rejected") for s in states):
                if sample.state in ("draft", "received", "to_verify"):
                    sample.state = "in_progress"

    def _can_auto_verify(self, qc_run=False):
        self.ensure_one()
        service = self.service_id
        self._evaluate_delta_check()
        if not service.auto_verify_enabled:
            self._set_manual_review_reason("auto_disabled", manual=False)
            return False
        if self.is_critical:
            self._set_manual_review_reason("critical", manual=True)
            return False
        if self.needs_manual_review:
            self._set_manual_review_reason("delta_fail", manual=True)
            return False
        if self.is_out_of_range and not service.auto_verify_allow_out_of_range:
            self._set_manual_review_reason("out_of_range", manual=True)
            return False
        if service.require_qc and service.auto_verify_require_qc_pass:
            if not qc_run:
                qc_run = self.env["lab.qc.run"].search(
                    [("service_id", "=", service.id)],
                    order="run_date desc, id desc",
                    limit=1,
                )
            if not qc_run or qc_run.status != "pass":
                self._set_manual_review_reason("qc_not_passed", manual=True)
                return False
        self._set_manual_review_reason(False, manual=False)
        return True

    def _evaluate_delta_check(self):
        self.ensure_one()
        service = self.service_id
        if (
            service.result_type != "numeric"
            or not service.delta_check_enabled
            or service.delta_check_threshold <= 0
            or self.result_value in (False, "")
        ):
            self.write(
                {
                    "delta_check_status": "na",
                    "delta_previous_value": 0.0,
                    "delta_check_value": 0.0,
                    "needs_manual_review": False,
                }
            )
            return

        try:
            current = float(self.result_value)
        except (TypeError, ValueError):
            self.write(
                {
                    "delta_check_status": "na",
                    "delta_previous_value": 0.0,
                    "delta_check_value": 0.0,
                    "needs_manual_review": False,
                }
            )
            return

        previous = self.env["lab.sample.analysis"].search(
            [
                ("id", "!=", self.id),
                ("service_id", "=", service.id),
                ("sample_id.patient_id", "=", self.sample_id.patient_id.id),
                ("sample_id.state", "in", ("verified", "reported")),
                ("state", "in", ("done", "verified")),
                ("result_value", "!=", False),
                ("result_value", "!=", ""),
            ],
            order="id desc",
            limit=1,
        )
        if not previous:
            self.write(
                {
                    "delta_check_status": "na",
                    "delta_previous_value": 0.0,
                    "delta_check_value": 0.0,
                    "needs_manual_review": False,
                }
            )
            return

        try:
            previous_value = float(previous.result_value)
        except (TypeError, ValueError):
            self.write(
                {
                    "delta_check_status": "na",
                    "delta_previous_value": 0.0,
                    "delta_check_value": 0.0,
                    "needs_manual_review": False,
                }
            )
            return

        if service.delta_check_method == "percent":
            if previous_value == 0:
                delta_value = abs(current - previous_value) * 100.0
            else:
                delta_value = abs((current - previous_value) / previous_value) * 100.0
        else:
            delta_value = abs(current - previous_value)

        passed = delta_value <= service.delta_check_threshold
        self.write(
            {
                "delta_previous_value": previous_value,
                "delta_check_value": delta_value,
                "delta_check_status": "pass" if passed else "fail",
                "needs_manual_review": not passed,
            }
        )

    def _set_manual_review_reason(self, reason_code, manual):
        self.ensure_one()
        if not reason_code:
            self.write(
                {
                    "manual_review_reason_code": False,
                    "manual_review_reason_note": False,
                    "manual_review_recommendation": False,
                    "needs_manual_review": False,
                    "review_due_date": False,
                    "review_assigned_user_id": False,
                    "review_assigned_date": False,
                }
            )
            return
        template = self.env["lab.review.reason.template"].search(
            [("code", "=", reason_code), ("active", "=", True)],
            limit=1,
        )
        note = template.message if template else reason_code
        recommendation = template.recommendation if template else False
        result_note = self.result_note or ""
        if template and template.append_to_result_note and recommendation:
            if recommendation not in result_note:
                result_note = (result_note + "\n" if result_note else "") + recommendation
        self.write(
            {
                "manual_review_reason_code": reason_code,
                "manual_review_reason_note": note,
                "manual_review_recommendation": recommendation,
                "needs_manual_review": manual,
                "review_due_date": (
                    fields.Datetime.add(fields.Datetime.now(), hours=template.sla_hours or 0)
                    if (manual and template and template.sla_hours)
                    else False
                ),
                "review_assigned_user_id": False,
                "review_assigned_date": False,
                "result_note": result_note,
            }
        )

    def action_claim_manual_review(self):
        for rec in self:
            if not rec.needs_manual_review or rec.state not in ("assigned", "done"):
                continue
            rec.write(
                {
                    "review_assigned_user_id": self.env.user.id,
                    "review_assigned_date": fields.Datetime.now(),
                }
            )
            rec.sample_id.message_post(
                body=_(
                    "Manual review for %(service)s claimed by %(user)s."
                ) % {"service": rec.service_id.name, "user": self.env.user.name},
                subtype_xmlid="mail.mt_note",
            )

    @api.model
    def _cron_notify_overdue_manual_reviews(self):
        overdue_lines = self.search(
            [
                ("needs_manual_review", "=", True),
                ("review_due_date", "!=", False),
                ("review_due_date", "<", fields.Datetime.now()),
                ("state", "in", ("assigned", "done")),
            ]
        )
        if not overdue_lines:
            return

        todo = self.env.ref("mail.mail_activity_data_todo")
        model_id = self.env["ir.model"]._get_id("lab.sample")
        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        users = reviewer_group.user_ids if (reviewer_group and reviewer_group.user_ids) else self.env.user

        for line in overdue_lines:
            summary = "Manual review overdue"
            note = (
                "Analysis %(analysis)s for sample %(sample)s is overdue for manual review. "
                "Due: %(due)s, reason: %(reason)s."
            ) % {
                "analysis": line.service_id.name,
                "sample": line.sample_id.name,
                "due": line.review_due_date,
                "reason": line.manual_review_reason_code or "-",
            }
            recipients = line.review_assigned_user_id if line.review_assigned_user_id else users
            for user in recipients:
                exists = self.env["mail.activity"].search_count(
                    [
                        ("res_model_id", "=", model_id),
                        ("res_id", "=", line.sample_id.id),
                        ("user_id", "=", user.id),
                        ("summary", "=", summary),
                    ]
                )
                if exists:
                    continue
                self.env["mail.activity"].create(
                    {
                        "activity_type_id": todo.id,
                        "user_id": user.id,
                        "res_model_id": model_id,
                        "res_id": line.sample_id.id,
                        "summary": summary,
                        "note": note,
                    }
                )

    @api.model
    def _cron_send_daily_manual_review_digest(self):
        today = fields.Date.context_today(self)
        report_day = today - timedelta(days=1)
        start_dt = datetime.combine(report_day, time.min)
        end_dt = datetime.combine(report_day, time.max)

        completed_domain = [
            ("manual_reviewed_date", ">=", fields.Datetime.to_string(start_dt)),
            ("manual_reviewed_date", "<=", fields.Datetime.to_string(end_dt)),
        ]
        pending_domain = [
            ("needs_manual_review", "=", True),
            ("state", "in", ("assigned", "done")),
        ]
        overdue_domain = pending_domain + [
            ("review_due_date", "!=", False),
            ("review_due_date", "<", fields.Datetime.now()),
        ]

        completed = self.search(completed_domain)
        pending = self.search(pending_domain)
        overdue = self.search(overdue_domain)

        reason_counts = {}
        for line in completed:
            code = line.manual_review_reason_code or "unclassified"
            reason_counts[code] = reason_counts.get(code, 0) + 1
        reason_rows = "".join(
            f"<li>{code}: {count}</li>" for code, count in sorted(reason_counts.items())
        ) or "<li>none</li>"

        config = self.env["lab.manual.review.digest.config"].search([("active", "=", True)], order="id", limit=1)
        if config:
            subject_tpl = config.subject_template
            body_tpl = config.body_template
        else:
            subject_tpl = "[Lab] Manual Review Daily Digest - {report_day}"
            body_tpl = (
                "<p>Manual review digest for <strong>{report_day}</strong></p>"
                "<ul>"
                "<li>Completed yesterday: {completed_count}</li>"
                "<li>Pending now: {pending_count}</li>"
                "<li>Overdue now: {overdue_count}</li>"
                "</ul>"
                "<p>Completed reason breakdown:</p>"
                "{reason_html}"
            )
        payload = {
            "report_day": str(report_day),
            "completed_count": len(completed),
            "pending_count": len(pending),
            "overdue_count": len(overdue),
            "reason_html": f"<ul>{reason_rows}</ul>",
        }
        subject = subject_tpl.format_map(payload)
        body = body_tpl.format_map(payload)

        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        recipients = reviewer_group.user_ids.filtered(lambda u: u.partner_id.email) if reviewer_group else self.env.user
        if config and config.fallback_email:
            fallback_emails = [x.strip() for x in (config.fallback_email or "").split(",") if x.strip()]
        else:
            fallback_emails = []
        if not recipients:
            if fallback_emails:
                for email in fallback_emails:
                    self.env["mail.mail"].create(
                        {
                            "email_to": email,
                            "subject": subject,
                            "body_html": body,
                        }
                    )
                return
            recipients = self.env["res.users"].search(
                [("active", "=", True), ("share", "=", False), ("partner_id.email", "!=", False)],
                limit=1,
            )
        for user in recipients:
            self.env["mail.mail"].create(
                {
                    "email_to": user.partner_id.email,
                    "subject": subject,
                    "body_html": body,
                }
            )

    def _create_critical_alert(self):
        self.ensure_one()
        sample = self.sample_id
        message = _(
            "Critical result detected: %(service)s = %(result)s %(unit)s (sample %(sample)s)"
        ) % {
            "service": self.service_id.name,
            "result": self.result_value,
            "unit": self.unit or "",
            "sample": sample.name,
        }
        sample.message_post(body=message, subtype_xmlid="mail.mt_note")

        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        todo = self.env.ref("mail.mail_activity_data_todo")
        users = reviewer_group.user_ids if (reviewer_group and reviewer_group.user_ids) else self.env.user
        for user in users:
            self.env["mail.activity"].create(
                {
                    "activity_type_id": todo.id,
                    "user_id": user.id,
                    "res_model_id": self.env["ir.model"]._get_id("lab.sample"),
                    "res_id": sample.id,
                    "summary": _("Critical result review required"),
                    "note": message,
                }
            )
        sample._auto_create_nonconformance(
            _("Critical Result: %s") % self.service_id.name,
            message,
            severity="critical",
            analysis=self,
        )


class LabSampleAmendment(models.Model):
    _name = "lab.sample.amendment"
    _description = "Lab Sample Amendment History"
    _order = "id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    revision = fields.Integer(required=True)
    note = fields.Text(required=True)
    amended_by_id = fields.Many2one("res.users", required=True)
    amended_date = fields.Datetime(required=True)


class LabSampleTimeline(models.Model):
    _name = "lab.sample.timeline"
    _description = "Lab Sample Timeline"
    _order = "event_time desc, id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    event_type = fields.Selection(
        [
            ("draft", "Draft"),
            ("received", "Received"),
            ("in_progress", "In Progress"),
            ("to_verify", "To Verify"),
            ("verified", "Verified"),
            ("reported", "Reported"),
            ("cancel", "Cancelled"),
            ("aliquot", "Aliquot"),
            ("retest", "Retest"),
            ("recollect", "Recollect"),
            ("amendment", "Amendment"),
        ],
        required=True,
    )
    event_time = fields.Datetime(required=True)
    user_id = fields.Many2one("res.users", required=True)
    note = fields.Char(required=True)


class LabSampleSignoff(models.Model):
    _name = "lab.sample.signoff"
    _description = "Lab Sample Electronic Sign-off"
    _order = "signed_at desc, id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    action_type = fields.Selection(
        [
            ("receive", "Receive"),
            ("start", "Start Analysis"),
            ("verify", "Verify"),
            ("release", "Release Report"),
            ("amend", "Amend Report"),
            ("retest", "Request Retest"),
            ("recollect", "Recollect"),
            ("aliquot", "Create Aliquot"),
            ("dispose", "Dispose Sample"),
        ],
        required=True,
    )
    signed_at = fields.Datetime(required=True)
    signed_by_id = fields.Many2one("res.users", required=True)
    signature_ref = fields.Char(required=True, copy=False)
    note = fields.Char(required=True)


class LabSampleCustody(models.Model):
    _name = "lab.sample.custody"
    _description = "Lab Sample Chain of Custody"
    _order = "event_time desc, id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    event_type = fields.Selection(
        [
            ("register", "Register"),
            ("receive", "Receive"),
            ("transfer", "Transfer"),
            ("release", "Release"),
            ("aliquot", "Aliquot"),
        ],
        required=True,
    )
    from_user_id = fields.Many2one("res.users", string="From User")
    to_user_id = fields.Many2one("res.users", string="To User")
    event_time = fields.Datetime(required=True)
    location = fields.Char()
    note = fields.Char(required=True)
