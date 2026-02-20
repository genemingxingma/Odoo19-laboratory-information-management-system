from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabSampleCustodyBatch(models.Model):
    _inherit = "lab.sample.custody.batch"

    receive_session_ids = fields.One2many("lab.custody.receive.session", "batch_id", string="Receive Sessions")
    receive_session_count = fields.Integer(compute="_compute_receive_session_count")
    investigation_ids = fields.One2many("lab.custody.investigation", "batch_id", string="Investigations")
    investigation_count = fields.Integer(compute="_compute_investigation_count")
    closure_state = fields.Selection(
        [
            ("open", "Open"),
            ("receiving", "Receiving"),
            ("investigating", "Investigating"),
            ("verifying", "Verifying"),
            ("closed", "Closed"),
        ],
        default="open",
        tracking=True,
    )
    closure_note = fields.Text()

    def _compute_receive_session_count(self):
        grouped = self.env["lab.custody.receive.session"].read_group(
            [("batch_id", "in", self.ids)], ["batch_id"], ["batch_id"]
        )
        count_map = {item["batch_id"][0]: item["batch_id_count"] for item in grouped if item.get("batch_id")}
        for batch in self:
            batch.receive_session_count = count_map.get(batch.id, 0)

    def _compute_investigation_count(self):
        grouped = self.env["lab.custody.investigation"].read_group(
            [("batch_id", "in", self.ids)], ["batch_id"], ["batch_id"]
        )
        count_map = {item["batch_id"][0]: item["batch_id_count"] for item in grouped if item.get("batch_id")}
        for batch in self:
            batch.investigation_count = count_map.get(batch.id, 0)

    def action_open_receive_wizard(self):
        self.ensure_one()
        return {
            "name": _("Create Receive Session"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.receive.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_batch_id": self.id,
                "default_receiver_id": self.to_user_id.id or self.env.user.id,
                "default_witness_id": self.from_user_id.id,
                "default_receive_temp": self.measured_temp_receive,
                "default_package_condition": self.package_condition,
            },
        }

    def action_view_receive_sessions(self):
        self.ensure_one()
        return {
            "name": _("Receive Sessions"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.receive.session",
            "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id},
        }

    def action_view_investigations(self):
        self.ensure_one()
        return {
            "name": _("Custody Investigations"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.investigation",
            "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {"default_batch_id": self.id},
        }

    def action_print_manifest(self):
        self.ensure_one()
        return self.env.ref("laboratory_management.action_report_lab_custody_manifest").report_action(self)

    def action_auto_create_investigations(self):
        for batch in self:
            for line in batch.line_ids.filtered(lambda x: x.state == "exception"):
                line.action_open_or_create_investigation()


class LabNonconformance(models.Model):
    _inherit = "lab.nonconformance"

    investigation_ids = fields.One2many("lab.custody.investigation", "nonconformance_id", string="Investigations")
    investigation_count = fields.Integer(compute="_compute_investigation_count")

    def _compute_investigation_count(self):
        grouped = self.env["lab.custody.investigation"].read_group(
            [("nonconformance_id", "in", self.ids)], ["nonconformance_id"], ["nonconformance_id"]
        )
        count_map = {
            item["nonconformance_id"][0]: item["nonconformance_id_count"]
            for item in grouped
            if item.get("nonconformance_id")
        }
        for ncr in self:
            ncr.investigation_count = count_map.get(ncr.id, 0)

    def action_view_investigations(self):
        self.ensure_one()
        return {
            "name": _("Investigations"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.investigation",
            "view_mode": "list,form",
            "domain": [("nonconformance_id", "=", self.id)],
            "context": {
                "default_nonconformance_id": self.id,
                "default_batch_id": self.custody_batch_id.id,
            },
        }


class LabSampleCustodyBatchLine(models.Model):
    _inherit = "lab.sample.custody.batch.line"

    receive_session_line_ids = fields.One2many("lab.custody.receive.session.line", "batch_line_id", string="Receipt Checks")
    investigation_ids = fields.One2many("lab.custody.investigation", "batch_line_id", string="Investigations")

    def action_open_or_create_investigation(self):
        self.ensure_one()
        investigation_obj = self.env["lab.custody.investigation"]
        existing = investigation_obj.search(
            [
                ("batch_line_id", "=", self.id),
                ("state", "in", ("draft", "open", "root_cause", "capa", "verification")),
            ],
            limit=1,
        )
        if not existing:
            if not self.nonconformance_id:
                self.action_create_nonconformance()
            existing = investigation_obj.create(
                {
                    "batch_id": self.batch_id.id,
                    "batch_line_id": self.id,
                    "sample_id": self.sample_id.id,
                    "nonconformance_id": self.nonconformance_id.id,
                    "owner_id": self.to_user_id.id or self.env.user.id,
                    "issue_summary": self.exception_detail
                    or (self.exception_template_id.description if self.exception_template_id else False)
                    or _("Custody exception requires investigation."),
                    "severity": self.exception_severity or "major",
                    "state": "open",
                }
            )
            self.batch_id.closure_state = "investigating"
        return {
            "name": _("Custody Investigation"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.investigation",
            "view_mode": "form",
            "res_id": existing.id,
            "target": "current",
        }


class LabCustodyReceiveSession(models.Model):
    _name = "lab.custody.receive.session"
    _description = "Lab Custody Receive Session"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True, tracking=True)
    batch_id = fields.Many2one("lab.sample.custody.batch", required=True, ondelete="cascade", tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    receiver_id = fields.Many2one("res.users", required=True, tracking=True)
    witness_id = fields.Many2one("res.users", required=True, tracking=True)
    qa_reviewer_id = fields.Many2one("res.users", tracking=True)
    started_at = fields.Datetime(readonly=True)
    submitted_at = fields.Datetime(readonly=True)
    approved_at = fields.Datetime(readonly=True)
    done_at = fields.Datetime(readonly=True)
    receive_temp = fields.Float(string="Measured Receive Temp (C)")
    package_condition = fields.Selection(
        [
            ("normal", "Normal"),
            ("damaged", "Damaged"),
            ("wet", "Wet/Contaminated"),
            ("tampered", "Tampered"),
        ],
        default="normal",
    )
    seal_intact = fields.Boolean(default=True)
    seal_note = fields.Char()
    checklist_result = fields.Selection(
        [("pending", "Pending"), ("ok", "Pass"), ("ng", "Not Pass")],
        default="pending",
        tracking=True,
    )
    note = fields.Text()

    line_ids = fields.One2many("lab.custody.receive.session.line", "session_id", string="Receipt Lines", copy=False)
    total_line_count = fields.Integer(compute="_compute_line_summary")
    ok_line_count = fields.Integer(compute="_compute_line_summary")
    discrepancy_line_count = fields.Integer(compute="_compute_line_summary")
    waived_line_count = fields.Integer(compute="_compute_line_summary")
    is_dual_confirmed = fields.Boolean(compute="_compute_is_dual_confirmed")

    @api.depends("line_ids.state")
    def _compute_line_summary(self):
        for rec in self:
            rec.total_line_count = len(rec.line_ids)
            rec.ok_line_count = len(rec.line_ids.filtered(lambda x: x.state == "ok"))
            rec.discrepancy_line_count = len(rec.line_ids.filtered(lambda x: x.state == "discrepancy"))
            rec.waived_line_count = len(rec.line_ids.filtered(lambda x: x.state == "waived"))

    @api.depends("receiver_id", "witness_id")
    def _compute_is_dual_confirmed(self):
        for rec in self:
            rec.is_dual_confirmed = bool(rec.receiver_id and rec.witness_id and rec.receiver_id != rec.witness_id)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.custody.receive.session") or "New"
            if not vals.get("receiver_id"):
                vals["receiver_id"] = self.env.user.id
            if not vals.get("witness_id"):
                vals["witness_id"] = self.env.user.id
        sessions = super().create(vals_list)
        for rec in sessions:
            if not rec.line_ids:
                rec._prefill_lines()
        return sessions

    @api.constrains("receiver_id", "witness_id")
    def _check_dual_confirmation(self):
        for rec in self:
            if rec.receiver_id and rec.witness_id and rec.receiver_id == rec.witness_id:
                raise ValidationError(_("Receiver and witness must be different users."))

    def _prefill_lines(self):
        self.ensure_one()
        line_vals = []
        for batch_line in self.batch_id.line_ids:
            line_vals.append(
                {
                    "session_id": self.id,
                    "batch_line_id": batch_line.id,
                    "sample_id": batch_line.sample_id.id,
                    "expected_present": True,
                    "actual_present": batch_line.state in ("in_transit", "done", "exception"),
                    "container_ok": batch_line.exception_template_id.code != "DAMAGED_PKG" if batch_line.exception_template_id else True,
                    "label_ok": True,
                    "quantity_ok": True,
                    "temperature_ok": True,
                    "state": "ok" if batch_line.state != "exception" else "discrepancy",
                    "discrepancy_type": "none" if batch_line.state != "exception" else "other",
                    "discrepancy_note": batch_line.exception_detail,
                    "nonconformance_id": batch_line.nonconformance_id.id,
                }
            )
        if line_vals:
            self.env["lab.custody.receive.session.line"].create(line_vals)

    def action_start(self):
        for rec in self:
            if rec.state not in ("draft", "rejected"):
                continue
            rec.write(
                {
                    "state": "in_progress",
                    "started_at": fields.Datetime.now(),
                }
            )
            rec.batch_id.write({"closure_state": "receiving"})

    def _validate_before_submit(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Receive session has no lines."))
        if self.receiver_id == self.witness_id:
            raise UserError(_("Receiver and witness cannot be the same user."))
        if self.batch_id.state not in ("in_transit", "received"):
            raise UserError(_("Batch must be in transit or received before submit."))
        unchecked = self.line_ids.filtered(lambda x: x.state not in ("ok", "discrepancy", "waived"))
        if unchecked:
            raise UserError(_("Some lines are not assessed."))

    def action_submit(self):
        for rec in self:
            rec._validate_before_submit()
            checklist_result = "ok"
            if rec.discrepancy_line_count > 0 or rec.package_condition in ("damaged", "wet", "tampered"):
                checklist_result = "ng"
            rec.write(
                {
                    "state": "submitted",
                    "submitted_at": fields.Datetime.now(),
                    "checklist_result": checklist_result,
                }
            )
            rec._create_approval_activity()

    def _create_approval_activity(self):
        self.ensure_one()
        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        users = reviewer_group.user_ids if reviewer_group and reviewer_group.user_ids else self.env.user
        summary = _("Approve custody receive session")
        entries = []
        for user in users:
            entries.append(
                {
                    "res_id": self.id,
                    "user_id": user.id,
                    "summary": summary,
                    "note": _("Session %(name)s for batch %(batch)s is waiting for QA approval.")
                    % {"name": self.name, "batch": self.batch_id.name},
                }
            )
        self.env["lab.activity.helper.mixin"].create_unique_todo_activities(
            model_name="lab.custody.receive.session",
            entries=entries,
        )

    def action_reject(self):
        for rec in self:
            if rec.state not in ("submitted", "approved"):
                continue
            rec.write({"state": "rejected"})

    def action_approve(self):
        for rec in self:
            if rec.state != "submitted":
                continue
            rec.write(
                {
                    "state": "approved",
                    "approved_at": fields.Datetime.now(),
                    "qa_reviewer_id": self.env.user.id,
                }
            )
            rec.batch_id._create_signoff("receive", _("Receive session %(session)s approved") % {"session": rec.name})
            if rec.discrepancy_line_count > 0:
                rec.batch_id.closure_state = "investigating"
            else:
                rec.batch_id.closure_state = "verifying"

    def action_finalize(self):
        for rec in self:
            if rec.state != "approved":
                continue
            for line in rec.line_ids.filtered(lambda x: x.state == "ok"):
                if line.batch_line_id.state == "in_transit":
                    line.batch_line_id.action_confirm_received()
            for line in rec.line_ids.filtered(lambda x: x.state == "discrepancy"):
                line._sync_exception_to_batch_line()
            rec.write({"state": "done", "done_at": fields.Datetime.now()})
            rec.batch_id.state = "received"
            open_investigations = self.env["lab.custody.investigation"].search_count(
                [
                    ("batch_id", "=", rec.batch_id.id),
                    ("state", "in", ("draft", "open", "root_cause", "capa", "verification")),
                ]
            )
            rec.batch_id.closure_state = "closed" if not open_investigations else "investigating"

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_view_receive_lines(self):
        self.ensure_one()
        return {
            "name": _("Receive Session Lines"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.receive.session.line",
            "view_mode": "list,form",
            "domain": [("session_id", "=", self.id)],
            "context": {"default_session_id": self.id},
        }


class LabCustodyReceiveSessionLine(models.Model):
    _name = "lab.custody.receive.session.line"
    _description = "Lab Custody Receive Session Line"
    _order = "id"

    session_id = fields.Many2one("lab.custody.receive.session", required=True, ondelete="cascade")
    batch_line_id = fields.Many2one("lab.sample.custody.batch.line", required=True, ondelete="cascade")
    sample_id = fields.Many2one("lab.sample", required=True, ondelete="restrict")

    expected_present = fields.Boolean(default=True)
    actual_present = fields.Boolean(default=True)
    container_ok = fields.Boolean(default=True)
    label_ok = fields.Boolean(default=True)
    quantity_ok = fields.Boolean(default=True)
    temperature_ok = fields.Boolean(default=True)

    discrepancy_type = fields.Selection(
        [
            ("none", "None"),
            ("missing", "Missing"),
            ("damage", "Damaged Container"),
            ("label", "Label Mismatch"),
            ("temperature", "Temperature Excursion"),
            ("other", "Other"),
        ],
        default="none",
        required=True,
    )
    discrepancy_note = fields.Text()
    state = fields.Selection(
        [("ok", "OK"), ("discrepancy", "Discrepancy"), ("waived", "Waived")],
        default="ok",
        required=True,
    )
    nonconformance_id = fields.Many2one("lab.nonconformance", string="Nonconformance", readonly=True, copy=False)

    @api.constrains("session_id", "batch_line_id")
    def _check_unique_batch_line(self):
        for line in self:
            count = self.search_count(
                [
                    ("session_id", "=", line.session_id.id),
                    ("batch_line_id", "=", line.batch_line_id.id),
                    ("id", "!=", line.id),
                ]
            )
            if count:
                raise ValidationError(_("A batch line can only appear once in one receive session."))

    @api.onchange("actual_present", "container_ok", "label_ok", "quantity_ok", "temperature_ok")
    def _onchange_flags(self):
        for line in self:
            if not all([line.actual_present, line.container_ok, line.label_ok, line.quantity_ok, line.temperature_ok]):
                line.state = "discrepancy"
                if not line.actual_present:
                    line.discrepancy_type = "missing"
                elif not line.container_ok:
                    line.discrepancy_type = "damage"
                elif not line.label_ok:
                    line.discrepancy_type = "label"
                elif not line.temperature_ok:
                    line.discrepancy_type = "temperature"
                else:
                    line.discrepancy_type = "other"
            elif line.state != "waived":
                line.state = "ok"
                line.discrepancy_type = "none"

    def action_mark_waived(self):
        self.write({"state": "waived"})

    def action_mark_discrepancy(self):
        for line in self:
            line.write({"state": "discrepancy"})
            line._sync_exception_to_batch_line()

    def _sync_exception_to_batch_line(self):
        self.ensure_one()
        batch_line = self.batch_line_id
        if self.state == "ok":
            return
        vals = {
            "state": "exception",
            "exception_date": batch_line.exception_date or fields.Datetime.now(),
            "exception_detail": self.discrepancy_note
            or _("Discrepancy from receive session %(session)s") % {"session": self.session_id.name},
        }
        severity = "major"
        if self.discrepancy_type in ("missing", "temperature"):
            severity = "critical"
        vals["exception_severity"] = severity
        batch_line.write(vals)
        if not batch_line.nonconformance_id:
            batch_line.action_create_nonconformance()
        self.nonconformance_id = batch_line.nonconformance_id.id


class LabCustodyInvestigation(models.Model):
    _name = "lab.custody.investigation"
    _description = "Lab Custody Investigation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True, tracking=True)
    batch_id = fields.Many2one("lab.sample.custody.batch", required=True, ondelete="cascade", tracking=True)
    batch_line_id = fields.Many2one("lab.sample.custody.batch.line", ondelete="set null", tracking=True)
    sample_id = fields.Many2one("lab.sample", tracking=True)
    nonconformance_id = fields.Many2one("lab.nonconformance", tracking=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("open", "Open"),
            ("root_cause", "Root Cause"),
            ("capa", "CAPA"),
            ("verification", "Verification"),
            ("closed", "Closed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    owner_id = fields.Many2one("res.users", string="Owner", required=True, default=lambda self: self.env.user)
    qa_reviewer_id = fields.Many2one("res.users", string="QA Reviewer")
    severity = fields.Selection(
        [
            ("minor", "Minor"),
            ("major", "Major"),
            ("critical", "Critical"),
        ],
        default="major",
        required=True,
        tracking=True,
    )
    detected_date = fields.Datetime(default=fields.Datetime.now, required=True)
    target_close_date = fields.Date()
    closed_date = fields.Datetime(readonly=True)
    closed_by_id = fields.Many2one("res.users", readonly=True)

    issue_summary = fields.Text(required=True)
    impact_assessment = fields.Text()
    immediate_containment = fields.Text()
    root_cause = fields.Text()
    corrective_action_plan = fields.Text()
    preventive_action_plan = fields.Text()
    verification_plan = fields.Text()
    verification_result = fields.Text()
    effectiveness_conclusion = fields.Text()
    closure_note = fields.Text()

    action_ids = fields.One2many("lab.custody.investigation.action", "investigation_id", string="Action Items")
    action_count = fields.Integer(compute="_compute_action_count")
    done_action_count = fields.Integer(compute="_compute_action_count")
    is_overdue = fields.Boolean(compute="_compute_is_overdue")

    @api.depends("action_ids.state")
    def _compute_action_count(self):
        for rec in self:
            rec.action_count = len(rec.action_ids)
            rec.done_action_count = len(rec.action_ids.filtered(lambda x: x.state == "done"))

    @api.depends("target_close_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = bool(
                rec.target_close_date
                and rec.target_close_date < today
                and rec.state not in ("closed", "cancel")
            )

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.custody.investigation") or "New"
            if vals.get("batch_line_id") and not vals.get("sample_id"):
                line = self.env["lab.sample.custody.batch.line"].browse(vals["batch_line_id"])
                vals["sample_id"] = line.sample_id.id
            if vals.get("batch_line_id") and not vals.get("nonconformance_id"):
                line = self.env["lab.sample.custody.batch.line"].browse(vals["batch_line_id"])
                vals["nonconformance_id"] = line.nonconformance_id.id
        records = super().create(vals_list)
        for rec in records:
            rec.batch_id.closure_state = "investigating"
            if rec.nonconformance_id and rec.nonconformance_id.state == "draft":
                rec.nonconformance_id.action_open()
        return records

    def action_open(self):
        self.write({"state": "open"})

    def action_start_root_cause(self):
        self.write({"state": "root_cause"})

    def action_plan_capa(self):
        self.write({"state": "capa"})
        for rec in self:
            rec._ensure_default_actions()
            if rec.nonconformance_id and rec.nonconformance_id.state in ("open", "investigation"):
                rec.nonconformance_id.action_plan_capa()

    def action_move_verification(self):
        for rec in self:
            if rec.action_ids and rec.action_ids.filtered(lambda x: x.state != "done"):
                raise UserError(_("All CAPA action items must be done before verification."))
            rec.state = "verification"

    def action_close(self):
        for rec in self:
            if rec.state != "verification":
                raise UserError(_("Only verification state can be closed."))
            rec.write(
                {
                    "state": "closed",
                    "closed_date": fields.Datetime.now(),
                    "closed_by_id": self.env.user.id,
                }
            )
            if rec.nonconformance_id and rec.nonconformance_id.state != "closed":
                if not rec.nonconformance_id.corrective_action:
                    rec.nonconformance_id.corrective_action = rec.corrective_action_plan or _("See investigation: %s") % rec.name
                if not rec.nonconformance_id.preventive_action:
                    rec.nonconformance_id.preventive_action = rec.preventive_action_plan or _("See investigation: %s") % rec.name
                rec.nonconformance_id.action_close()
            open_cases = self.search_count(
                [
                    ("batch_id", "=", rec.batch_id.id),
                    ("state", "in", ("draft", "open", "root_cause", "capa", "verification")),
                ]
            )
            rec.batch_id.closure_state = "closed" if open_cases == 0 else "investigating"

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_print_summary(self):
        self.ensure_one()
        return self.env.ref("laboratory_management.action_report_lab_custody_investigation").report_action(self)

    def action_view_actions(self):
        self.ensure_one()
        return {
            "name": _("Investigation Actions"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.investigation.action",
            "view_mode": "list,form",
            "domain": [("investigation_id", "=", self.id)],
            "context": {"default_investigation_id": self.id},
        }

    def _ensure_default_actions(self):
        self.ensure_one()
        if self.action_ids:
            return
        action_obj = self.env["lab.custody.investigation.action"]
        defaults = [
            _("Containment confirmation"),
            _("Root cause verification"),
            _("Corrective implementation"),
            _("Preventive implementation"),
            _("Effectiveness review"),
        ]
        for idx, title in enumerate(defaults, start=1):
            action_obj.create(
                {
                    "investigation_id": self.id,
                    "sequence": idx * 10,
                    "name": title,
                    "owner_id": self.owner_id.id,
                    "due_date": self.target_close_date,
                }
            )

    @api.model
    def _cron_notify_overdue_investigations(self):
        overdue = self.search(
            [
                ("target_close_date", "!", False),
                ("target_close_date", "<", fields.Date.today()),
                ("state", "not in", ("closed", "cancel")),
            ]
        )
        if not overdue:
            return
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for inv in overdue:
            for user in (inv.owner_id | inv.qa_reviewer_id | self.env.user):
                entries.append(
                    {
                        "res_id": inv.id,
                        "user_id": user.id,
                        "summary": "Overdue custody investigation",
                        "note": _("Investigation %(name)s is overdue since %(date)s")
                        % {"name": inv.name, "date": inv.target_close_date},
                    }
                )
        helper.create_unique_todo_activities(
            model_name="lab.custody.investigation",
            entries=entries,
        )


class LabCustodyInvestigationAction(models.Model):
    _name = "lab.custody.investigation.action"
    _description = "Lab Custody Investigation Action"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    investigation_id = fields.Many2one("lab.custody.investigation", required=True, ondelete="cascade")
    name = fields.Char(required=True)
    description = fields.Text()
    owner_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    due_date = fields.Date()
    done_date = fields.Datetime(readonly=True)
    state = fields.Selection(
        [
            ("todo", "To Do"),
            ("doing", "In Progress"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="todo",
        required=True,
    )
    result_note = fields.Text()

    def action_start(self):
        self.write({"state": "doing"})

    def action_done(self):
        self.write({"state": "done", "done_date": fields.Datetime.now()})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_reset_todo(self):
        self.write({"state": "todo", "done_date": False})


class LabCustodyReceiveWizard(models.TransientModel):
    _name = "lab.custody.receive.wizard"
    _description = "Create Custody Receive Session Wizard"

    batch_id = fields.Many2one("lab.sample.custody.batch", required=True)
    receiver_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    witness_id = fields.Many2one("res.users", required=True)
    receive_temp = fields.Float(string="Measured Receive Temp (C)")
    package_condition = fields.Selection(
        [
            ("normal", "Normal"),
            ("damaged", "Damaged"),
            ("wet", "Wet/Contaminated"),
            ("tampered", "Tampered"),
        ],
        default="normal",
        required=True,
    )
    seal_intact = fields.Boolean(default=True)
    seal_note = fields.Char()
    note = fields.Text()
    auto_start = fields.Boolean(default=True)

    def action_create_session(self):
        self.ensure_one()
        if self.receiver_id == self.witness_id:
            raise UserError(_("Receiver and witness must be different users."))
        session = self.env["lab.custody.receive.session"].create(
            {
                "batch_id": self.batch_id.id,
                "receiver_id": self.receiver_id.id,
                "witness_id": self.witness_id.id,
                "receive_temp": self.receive_temp,
                "package_condition": self.package_condition,
                "seal_intact": self.seal_intact,
                "seal_note": self.seal_note,
                "note": self.note,
            }
        )
        if self.auto_start:
            session.action_start()
        return {
            "name": _("Receive Session"),
            "type": "ir.actions.act_window",
            "res_model": "lab.custody.receive.session",
            "view_mode": "form",
            "res_id": session.id,
            "target": "current",
        }
