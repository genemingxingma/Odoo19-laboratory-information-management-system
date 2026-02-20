from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabSample(models.Model):
    _inherit = "lab.sample"

    custody_batch_line_ids = fields.One2many("lab.sample.custody.batch.line", "sample_id", string="Custody Batch Lines", readonly=True)
    custody_batch_count = fields.Integer(compute="_compute_custody_batch_count")

    def _compute_custody_batch_count(self):
        grouped = self.env["lab.sample.custody.batch.line"].read_group(
            [("sample_id", "in", self.ids)], ["sample_id"], ["sample_id"]
        )
        counts = {item["sample_id"][0]: item["sample_id_count"] for item in grouped if item.get("sample_id")}
        for sample in self:
            sample.custody_batch_count = counts.get(sample.id, 0)

    def action_view_custody_batches(self):
        self.ensure_one()
        lines = self.env["lab.sample.custody.batch.line"].search([("sample_id", "=", self.id)])
        return {
            "name": _("Custody Batches"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sample.custody.batch",
            "view_mode": "list,form",
            "domain": [("id", "in", lines.mapped("batch_id").ids)],
            "context": {
                "default_from_user_id": self.current_custodian_id.id or self.env.user.id,
                "default_from_location": self.custody_location,
            },
        }


class LabSampleCustody(models.Model):
    _inherit = "lab.sample.custody"

    event_type = fields.Selection(
        selection_add=[
            ("dispatch", "Dispatch"),
            ("handover_ack", "Handover Acknowledged"),
        ],
        ondelete={
            "dispatch": "cascade",
            "handover_ack": "cascade",
        },
    )
    batch_id = fields.Many2one("lab.sample.custody.batch", string="Custody Batch", ondelete="set null", copy=False)
    transport_tracking = fields.Char(string="Transport Tracking")
    package_condition = fields.Selection(
        [
            ("normal", "Normal"),
            ("damaged", "Damaged"),
            ("wet", "Wet/Contaminated"),
            ("tampered", "Tampered"),
        ],
        default="normal",
    )
    transport_temperature = fields.Float(string="Transport Temperature (C)")
    seal_code = fields.Char(string="Seal Code")


class LabNonconformance(models.Model):
    _inherit = "lab.nonconformance"

    source_type = fields.Selection(
        selection_add=[("custody", "Custody")],
        ondelete={"custody": "set default"},
    )
    custody_batch_id = fields.Many2one("lab.sample.custody.batch", string="Custody Batch", tracking=True)
    custody_batch_line_id = fields.Many2one("lab.sample.custody.batch.line", string="Custody Batch Line", tracking=True)


class LabCustodyExceptionTemplate(models.Model):
    _name = "lab.custody.exception.template"
    _description = "Lab Custody Exception Template"
    _order = "sequence, id"

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    description = fields.Text()
    default_severity = fields.Selection(
        [
            ("minor", "Minor"),
            ("major", "Major"),
            ("critical", "Critical"),
        ],
        default="major",
        required=True,
    )

    @api.constrains("code")
    def _check_code_unique(self):
        for rec in self:
            if not rec.code:
                continue
            count = self.search_count([("code", "=", rec.code), ("id", "!=", rec.id)])
            if count:
                raise ValidationError(_("Exception template code must be unique."))


class LabSampleCustodyBatch(models.Model):
    _name = "lab.sample.custody.batch"
    _description = "Lab Sample Custody Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Batch Reference", default="New", copy=False, readonly=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_transit", "In Transit"),
            ("received", "Received"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    from_user_id = fields.Many2one("res.users", string="From Custodian", required=True, tracking=True)
    to_user_id = fields.Many2one("res.users", string="To Custodian", required=True, tracking=True)
    from_location = fields.Char(string="From Location", tracking=True)
    to_location = fields.Char(string="To Location", tracking=True)
    dispatch_time = fields.Datetime(tracking=True)
    received_time = fields.Datetime(tracking=True)
    courier_name = fields.Char(string="Courier Name")
    courier_phone = fields.Char(string="Courier Phone")
    tracking_number = fields.Char(string="Tracking Number")
    package_count = fields.Integer(default=1)
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
    expected_temp_min = fields.Float(string="Expected Temp Min (C)")
    expected_temp_max = fields.Float(string="Expected Temp Max (C)")
    measured_temp_dispatch = fields.Float(string="Dispatch Temperature (C)")
    measured_temp_receive = fields.Float(string="Receive Temperature (C)")
    seal_code = fields.Char(string="Seal Code")
    auto_ncr_on_exception = fields.Boolean(string="Auto Create NCR for Exception", default=True)
    note = fields.Text()

    line_ids = fields.One2many("lab.sample.custody.batch.line", "batch_id", string="Batch Samples", copy=False)
    signoff_ids = fields.One2many("lab.sample.custody.batch.signoff", "batch_id", string="Sign-offs", readonly=True)
    sample_count = fields.Integer(compute="_compute_sample_count")
    in_transit_count = fields.Integer(compute="_compute_line_state_count")
    done_count = fields.Integer(compute="_compute_line_state_count")
    exception_count = fields.Integer(compute="_compute_line_state_count")
    nonconformance_count = fields.Integer(compute="_compute_nonconformance_count")
    signoff_count = fields.Integer(compute="_compute_signoff_count")

    @api.depends("line_ids")
    def _compute_sample_count(self):
        for batch in self:
            batch.sample_count = len(batch.line_ids)

    @api.depends("line_ids.state")
    def _compute_line_state_count(self):
        for batch in self:
            batch.in_transit_count = len(batch.line_ids.filtered(lambda x: x.state == "in_transit"))
            batch.done_count = len(batch.line_ids.filtered(lambda x: x.state == "done"))
            batch.exception_count = len(batch.line_ids.filtered(lambda x: x.state == "exception"))

    def _compute_nonconformance_count(self):
        grouped = self.env["lab.nonconformance"].read_group(
            [("custody_batch_id", "in", self.ids)], ["custody_batch_id"], ["custody_batch_id"]
        )
        count_map = {
            item["custody_batch_id"][0]: item["custody_batch_id_count"]
            for item in grouped
            if item.get("custody_batch_id")
        }
        for batch in self:
            batch.nonconformance_count = count_map.get(batch.id, 0)

    def _compute_signoff_count(self):
        grouped = self.env["lab.sample.custody.batch.signoff"].read_group(
            [("batch_id", "in", self.ids)], ["batch_id"], ["batch_id"]
        )
        count_map = {
            item["batch_id"][0]: item["batch_id_count"]
            for item in grouped
            if item.get("batch_id")
        }
        for batch in self:
            batch.signoff_count = count_map.get(batch.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.sample.custody.batch") or "New"
            if not vals.get("from_user_id"):
                vals["from_user_id"] = self.env.user.id
            if not vals.get("from_location"):
                vals["from_location"] = self.env.user.partner_id.name or ""
        return super().create(vals_list)

    def action_add_active_samples(self):
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            raise UserError(_("Please select samples from list view first."))
        self.ensure_one()
        self._add_samples(active_ids)
        return True

    def _add_samples(self, sample_ids):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(_("Only draft batches can be modified."))
        samples = self.env["lab.sample"].browse(sample_ids).exists()
        if not samples:
            raise UserError(_("No valid sample found."))
        existing_ids = set(self.line_ids.mapped("sample_id").ids)
        lines_to_create = []
        for sample in samples:
            if sample.id in existing_ids:
                continue
            lines_to_create.append(
                {
                    "batch_id": self.id,
                    "sample_id": sample.id,
                    "from_user_id": sample.current_custodian_id.id,
                    "from_location": sample.custody_location,
                    "to_user_id": self.to_user_id.id,
                    "to_location": self.to_location,
                    "state": "draft",
                }
            )
        if lines_to_create:
            self.env["lab.sample.custody.batch.line"].create(lines_to_create)

    def _validate_before_dispatch(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Add at least one sample to the batch before dispatch."))
        if self.from_user_id == self.to_user_id:
            raise UserError(_("From/To custodian cannot be the same user."))
        invalid_lines = self.line_ids.filtered(
            lambda x: x.sample_id.current_custodian_id and x.sample_id.current_custodian_id != self.from_user_id
        )
        if invalid_lines:
            raise UserError(
                _("Some samples are no longer under current from-custodian: %s")
                % ", ".join(invalid_lines.mapped("sample_id.name"))
            )

    def action_dispatch(self):
        for batch in self:
            if batch.state != "draft":
                continue
            batch._validate_before_dispatch()
            dispatch_dt = fields.Datetime.now()
            for line in batch.line_ids:
                line._action_dispatch_line(dispatch_dt)
            batch.write({"state": "in_transit", "dispatch_time": dispatch_dt})
            batch._create_signoff("dispatch", _("Batch dispatched to %(to)s") % {"to": batch.to_user_id.name})
            batch.message_post(body=_("Custody batch dispatched with %(count)s sample(s).") % {"count": batch.sample_count})

    def action_mark_received(self):
        for batch in self:
            if batch.state != "in_transit":
                continue
            received_dt = fields.Datetime.now()
            pending_lines = batch.line_ids.filtered(lambda x: x.state == "in_transit")
            for line in pending_lines:
                line.action_confirm_received()
            batch.write({"state": "received", "received_time": received_dt})
            batch._create_signoff("receive", _("Batch received by %(user)s") % {"user": self.env.user.name})
            batch.message_post(body=_("Custody batch fully received."))

    def action_cancel(self):
        for batch in self:
            if batch.state == "received":
                raise UserError(_("Received batch cannot be cancelled."))
            batch.state = "cancel"

    def action_reset_draft(self):
        for batch in self:
            if batch.state != "cancel":
                continue
            batch.line_ids.write({"state": "draft"})
            batch.write({"state": "draft", "dispatch_time": False, "received_time": False})

    def action_create_exception_ncrs(self):
        for batch in self:
            for line in batch.line_ids.filtered(lambda x: x.state == "exception" and not x.nonconformance_id):
                line.action_create_nonconformance()
            batch._create_signoff("qa_review", _("Exception lines reviewed and NCR synchronized"))

    def action_view_nonconformances(self):
        self.ensure_one()
        return {
            "name": _("Custody Nonconformances"),
            "type": "ir.actions.act_window",
            "res_model": "lab.nonconformance",
            "view_mode": "list,form",
            "domain": [("custody_batch_id", "=", self.id)],
            "context": {
                "default_source_type": "custody",
                "default_custody_batch_id": self.id,
            },
        }

    def action_view_signoffs(self):
        self.ensure_one()
        return {
            "name": _("Custody Sign-offs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.sample.custody.batch.signoff",
            "view_mode": "list,form",
            "domain": [("batch_id", "=", self.id)],
            "context": {
                "default_batch_id": self.id,
            },
        }

    def _create_signoff(self, action_type, note):
        self.ensure_one()
        self.env["lab.sample.custody.batch.signoff"].create(
            {
                "batch_id": self.id,
                "action_type": action_type,
                "signed_at": fields.Datetime.now(),
                "signed_by_id": self.env.user.id,
                "signature_ref": str(uuid4()),
                "note": note,
            }
        )

    def _notify_exception_activity(self, line):
        self.ensure_one()
        summary = _("Custody Exception Review")
        note = _(
            "Batch %(batch)s / Sample %(sample)s has custody exception (%(severity)s). Please assess and process NCR."
        ) % {
            "batch": self.name,
            "sample": line.sample_id.name,
            "severity": line.exception_severity or "major",
        }
        users = self.env["res.users"]
        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        manager_group = self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
        if reviewer_group:
            users |= reviewer_group.user_ids
        if manager_group:
            users |= manager_group.user_ids
        if not users:
            users = self.env.user
        entries = []
        for user in users:
            entries.append({"res_id": self.id, "user_id": user.id, "summary": summary, "note": note})
        self.env["lab.activity.helper.mixin"].create_unique_todo_activities(
            model_name="lab.sample.custody.batch",
            entries=entries,
        )


class LabSampleCustodyBatchSignoff(models.Model):
    _name = "lab.sample.custody.batch.signoff"
    _description = "Lab Sample Custody Batch Sign-off"
    _order = "signed_at desc, id desc"

    batch_id = fields.Many2one("lab.sample.custody.batch", required=True, ondelete="cascade")
    action_type = fields.Selection(
        [
            ("dispatch", "Dispatch"),
            ("receive", "Receive"),
            ("qa_review", "QA Review"),
        ],
        required=True,
    )
    signed_at = fields.Datetime(required=True)
    signed_by_id = fields.Many2one("res.users", required=True)
    signature_ref = fields.Char(required=True, copy=False)
    note = fields.Char(required=True)


class LabSampleCustodyBatchLine(models.Model):
    _name = "lab.sample.custody.batch.line"
    _description = "Lab Sample Custody Batch Line"
    _order = "id"

    batch_id = fields.Many2one("lab.sample.custody.batch", required=True, ondelete="cascade")
    sample_id = fields.Many2one("lab.sample", required=True, ondelete="restrict")
    from_user_id = fields.Many2one("res.users", string="From")
    to_user_id = fields.Many2one("res.users", string="To")
    from_location = fields.Char(string="From Location")
    to_location = fields.Char(string="To Location")
    event_id = fields.Many2one("lab.sample.custody", string="Last Custody Event", readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_transit", "In Transit"),
            ("done", "Done"),
            ("exception", "Exception"),
        ],
        default="draft",
        required=True,
    )
    receive_note = fields.Char()
    exception_date = fields.Datetime(readonly=True)
    exception_template_id = fields.Many2one("lab.custody.exception.template", string="Exception Type")
    exception_detail = fields.Text()
    exception_severity = fields.Selection(
        [
            ("minor", "Minor"),
            ("major", "Major"),
            ("critical", "Critical"),
        ],
        default="major",
    )
    nonconformance_id = fields.Many2one("lab.nonconformance", string="Nonconformance", readonly=True, copy=False)

    @api.constrains("batch_id", "sample_id")
    def _check_unique_sample_in_batch(self):
        for line in self:
            if not line.batch_id or not line.sample_id:
                continue
            duplicate_count = self.search_count(
                [
                    ("batch_id", "=", line.batch_id.id),
                    ("sample_id", "=", line.sample_id.id),
                    ("id", "!=", line.id),
                ]
            )
            if duplicate_count:
                raise ValidationError(_("A sample can only appear once in a custody batch."))

    @api.onchange("exception_template_id")
    def _onchange_exception_template_id(self):
        for line in self:
            if not line.exception_template_id:
                continue
            line.exception_severity = line.exception_template_id.default_severity
            if not line.exception_detail:
                line.exception_detail = line.exception_template_id.description

    def _action_dispatch_line(self, dispatch_dt):
        self.ensure_one()
        sample = self.sample_id
        note = _("Dispatched in custody batch %(batch)s") % {"batch": self.batch_id.name}
        sample.write(
            {
                "current_custodian_id": self.to_user_id.id,
                "custody_location": self.to_location,
            }
        )
        event = self.env["lab.sample.custody"].create(
            {
                "sample_id": sample.id,
                "event_type": "dispatch",
                "from_user_id": self.from_user_id.id,
                "to_user_id": self.to_user_id.id,
                "event_time": dispatch_dt,
                "location": self.to_location,
                "note": note,
                "batch_id": self.batch_id.id,
                "transport_tracking": self.batch_id.tracking_number,
                "package_condition": self.batch_id.package_condition,
                "transport_temperature": self.batch_id.measured_temp_dispatch,
                "seal_code": self.batch_id.seal_code,
            }
        )
        self.write({"state": "in_transit", "event_id": event.id})

    def action_confirm_received(self):
        for line in self:
            if line.state != "in_transit":
                continue
            sample = line.sample_id
            note = line.receive_note or _("Batch %(batch)s handover confirmed") % {"batch": line.batch_id.name}
            event = self.env["lab.sample.custody"].create(
                {
                    "sample_id": sample.id,
                    "event_type": "handover_ack",
                    "from_user_id": line.from_user_id.id,
                    "to_user_id": line.to_user_id.id,
                    "event_time": fields.Datetime.now(),
                    "location": line.to_location,
                    "note": note,
                    "batch_id": line.batch_id.id,
                    "transport_tracking": line.batch_id.tracking_number,
                    "package_condition": line.batch_id.package_condition,
                    "transport_temperature": line.batch_id.measured_temp_receive,
                    "seal_code": line.batch_id.seal_code,
                }
            )
            line.write({"state": "done", "event_id": event.id})

    def _build_exception_summary(self):
        self.ensure_one()
        summary = self.exception_template_id.name if self.exception_template_id else _("Custody exception")
        details = [
            _("Batch: %s") % self.batch_id.name,
            _("Sample: %s") % self.sample_id.name,
            _("From/To: %s -> %s") % (self.from_user_id.name or "-", self.to_user_id.name or "-"),
            _("Location: %s -> %s") % (self.from_location or "-", self.to_location or "-"),
            _("Tracking: %s") % (self.batch_id.tracking_number or "-"),
            _("Package condition: %s") % (self.batch_id.package_condition or "normal"),
            _("Dispatch temp: %s") % (self.batch_id.measured_temp_dispatch or 0.0),
            _("Receive temp: %s") % (self.batch_id.measured_temp_receive or 0.0),
        ]
        if self.exception_detail:
            details.append(_("Exception detail: %s") % self.exception_detail)
        return summary, "\n".join(details)

    def action_create_nonconformance(self):
        ncr_obj = self.env["lab.nonconformance"]
        for line in self:
            if line.nonconformance_id:
                continue
            title, description = line._build_exception_summary()
            existing = ncr_obj.search(
                [
                    ("source_type", "=", "custody"),
                    ("custody_batch_line_id", "=", line.id),
                    ("state", "in", ("draft", "open", "investigation", "capa")),
                ],
                limit=1,
            )
            if existing:
                line.nonconformance_id = existing.id
                continue
            ncr = ncr_obj.create(
                {
                    "title": title,
                    "description": description,
                    "source_type": "custody",
                    "sample_id": line.sample_id.id,
                    "owner_id": line.to_user_id.id or line.batch_id.to_user_id.id,
                    "severity": line.exception_severity or "major",
                    "state": "open",
                    "custody_batch_id": line.batch_id.id,
                    "custody_batch_line_id": line.id,
                }
            )
            line.nonconformance_id = ncr.id

    def action_mark_exception(self):
        for line in self:
            vals = {
                "state": "exception",
                "exception_date": line.exception_date or fields.Datetime.now(),
            }
            if line.exception_template_id and not line.exception_severity:
                vals["exception_severity"] = line.exception_template_id.default_severity
            line.write(vals)
            if line.batch_id.auto_ncr_on_exception and not line.nonconformance_id:
                line.action_create_nonconformance()
            line.batch_id._notify_exception_activity(line)
