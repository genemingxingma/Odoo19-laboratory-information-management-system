from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabStorageLocation(models.Model):
    _name = "lab.storage.location"
    _description = "Laboratory Storage Location"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    zone = fields.Selection(
        [
            ("ambient", "Ambient"),
            ("fridge", "Fridge"),
            ("freezer_20", "Freezer -20C"),
            ("freezer_80", "Freezer -80C"),
            ("liquid_n2", "Liquid Nitrogen"),
            ("other", "Other"),
        ],
        required=True,
        default="fridge",
    )
    temperature_min = fields.Float(string="Min Temp (C)")
    temperature_max = fields.Float(string="Max Temp (C)")
    capacity = fields.Integer(string="Capacity (Samples)", default=0)
    active = fields.Boolean(default=True)
    note = fields.Text()

    current_sample_count = fields.Integer(compute="_compute_current_sample_count")
    occupancy_rate = fields.Float(compute="_compute_current_sample_count")

    _code_uniq = models.Constraint("unique(code)", "Storage location code must be unique.")

    def _compute_current_sample_count(self):
        sample_obj = self.env["lab.sample"]
        for rec in self:
            count = sample_obj.search_count(
                [
                    ("storage_state", "=", "stored"),
                    ("storage_location_id", "=", rec.id),
                ]
            )
            rec.current_sample_count = count
            rec.occupancy_rate = (count / rec.capacity * 100.0) if rec.capacity else 0.0

    @api.constrains("temperature_min", "temperature_max")
    def _check_temperature_range(self):
        for rec in self:
            if (
                rec.temperature_min not in (False, None)
                and rec.temperature_max not in (False, None)
                and rec.temperature_min > rec.temperature_max
            ):
                raise ValidationError(_("Min temperature cannot exceed max temperature."))

    def action_view_samples(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Stored Samples"),
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [
                ("storage_state", "=", "stored"),
                ("storage_location_id", "=", self.id),
            ],
        }


class LabSample(models.Model):
    _inherit = "lab.sample"

    storage_state = fields.Selection(
        [
            ("not_stored", "Not Stored"),
            ("stored", "Stored"),
            ("retrieved", "Retrieved"),
            ("disposed", "Disposed"),
        ],
        default="not_stored",
        tracking=True,
    )
    storage_location_id = fields.Many2one("lab.storage.location", string="Storage Location", tracking=True)
    storage_box = fields.Char(string="Storage Box", tracking=True)
    storage_slot = fields.Char(string="Storage Slot", tracking=True)
    storage_stored_date = fields.Datetime(readonly=True, tracking=True)
    storage_retrieved_date = fields.Datetime(readonly=True, tracking=True)
    storage_disposed_date = fields.Datetime(readonly=True, tracking=True)
    storage_retention_days = fields.Integer(default=30, string="Retention Days")
    storage_due_date = fields.Datetime(compute="_compute_storage_due_date", store=True)
    storage_is_overdue = fields.Boolean(compute="_compute_storage_is_overdue", search="_search_storage_is_overdue")
    storage_note = fields.Text()

    storage_event_ids = fields.One2many("lab.sample.storage.event", "sample_id", string="Storage Events", readonly=True)
    disposal_record_ids = fields.One2many("lab.sample.disposal.record", "sample_id", string="Disposal Records", readonly=True)
    storage_event_count = fields.Integer(compute="_compute_storage_event_count")
    disposal_record_count = fields.Integer(compute="_compute_storage_event_count")

    @api.depends("storage_stored_date", "storage_retention_days", "storage_state")
    def _compute_storage_due_date(self):
        for rec in self:
            if rec.storage_state not in ("stored", "retrieved") or not rec.storage_stored_date:
                rec.storage_due_date = False
                continue
            rec.storage_due_date = fields.Datetime.add(rec.storage_stored_date, days=rec.storage_retention_days or 0)

    def _compute_storage_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.storage_is_overdue = bool(
                rec.storage_state in ("stored", "retrieved")
                and rec.storage_due_date
                and rec.storage_due_date < now
            )

    def _search_storage_is_overdue(self, operator, value):
        now = fields.Datetime.now()
        overdue_domain = [
            ("storage_state", "in", ("stored", "retrieved")),
            ("storage_due_date", "!=", False),
            ("storage_due_date", "<", now),
        ]
        not_overdue_domain = [
            "|",
            ("storage_state", "not in", ("stored", "retrieved")),
            "|",
            ("storage_due_date", "=", False),
            ("storage_due_date", ">=", now),
        ]
        if operator in ("=", "=="):
            return overdue_domain if value else not_overdue_domain
        if operator == "!=":
            return not_overdue_domain if value else overdue_domain
        return overdue_domain

    def _compute_storage_event_count(self):
        for rec in self:
            rec.storage_event_count = len(rec.storage_event_ids)
            rec.disposal_record_count = len(rec.disposal_record_ids)

    def action_view_storage_events(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Storage Events"),
            "res_model": "lab.sample.storage.event",
            "view_mode": "list,form",
            "domain": [("sample_id", "=", self.id)],
            "context": {"default_sample_id": self.id},
        }

    def action_view_disposal_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Disposal Records"),
            "res_model": "lab.sample.disposal.record",
            "view_mode": "list,form",
            "domain": [("sample_id", "=", self.id)],
            "context": {"default_sample_id": self.id},
        }

    def action_store_sample(self):
        for rec in self:
            rec._apply_store_sample(
                location=rec.storage_location_id,
                box=rec.storage_box,
                slot=rec.storage_slot,
                note=rec.storage_note or _("Stored from sample form"),
            )

    def action_retrieve_sample(self):
        for rec in self:
            rec._apply_retrieve_sample(note=rec.storage_note or _("Retrieved for further processing"))

    def action_return_to_storage(self):
        for rec in self:
            rec._apply_return_sample(note=rec.storage_note or _("Returned to storage after retrieval"))

    def action_dispose_sample(self):
        for rec in self:
            rec._apply_dispose_sample(
                method="other",
                reason=_("Routine disposal"),
                witness_name=False,
                note=rec.storage_note or _("Disposed from sample form"),
            )

    def _apply_store_sample(self, location, box=False, slot=False, note=False):
        self.ensure_one()
        if self.state in ("draft", "cancel"):
            raise UserError(_("Sample must be received or beyond before storage."))
        if not location:
            raise UserError(_("Please select storage location."))
        if self.storage_state == "disposed":
            raise UserError(_("Disposed samples cannot be moved back to storage."))
        from_location = self.storage_location_id
        event_type = "move" if self.storage_state == "stored" else "store"
        vals = {
            "storage_state": "stored",
            "storage_location_id": location.id,
            "storage_box": box or False,
            "storage_slot": slot or False,
            "storage_retrieved_date": False,
        }
        if not self.storage_stored_date:
            vals["storage_stored_date"] = fields.Datetime.now()
        self.write(vals)
        self._create_storage_event(
            event_type=event_type,
            from_location=from_location,
            to_location=location,
            box=box,
            slot=slot,
            note=note or _("Sample stored"),
        )

    def _apply_retrieve_sample(self, note=False):
        self.ensure_one()
        if self.storage_state != "stored":
            raise UserError(_("Only stored samples can be retrieved."))
        self.write(
            {
                "storage_state": "retrieved",
                "storage_retrieved_date": fields.Datetime.now(),
            }
        )
        self._create_storage_event(
            event_type="retrieve",
            from_location=self.storage_location_id,
            to_location=False,
            box=self.storage_box,
            slot=self.storage_slot,
            note=note or _("Sample retrieved"),
        )

    def _apply_return_sample(self, note=False):
        self.ensure_one()
        if self.storage_state != "retrieved":
            raise UserError(_("Only retrieved samples can be returned to storage."))
        if not self.storage_location_id:
            raise UserError(_("Storage location is required for return operation."))
        self.write(
            {
                "storage_state": "stored",
                "storage_retrieved_date": False,
            }
        )
        self._create_storage_event(
            event_type="return",
            from_location=False,
            to_location=self.storage_location_id,
            box=self.storage_box,
            slot=self.storage_slot,
            note=note or _("Sample returned to storage"),
        )

    def _apply_dispose_sample(self, method, reason, witness_name=False, note=False):
        self.ensure_one()
        if self.storage_state not in ("stored", "retrieved"):
            raise UserError(_("Only stored/retrieved samples can be disposed."))
        disposal = self.env["lab.sample.disposal.record"].create(
            {
                "sample_id": self.id,
                "disposal_date": fields.Datetime.now(),
                "disposed_by_id": self.env.user.id,
                "method": method,
                "reason": reason,
                "witness_name": witness_name or False,
                "note": note or False,
            }
        )
        self.write(
            {
                "storage_state": "disposed",
                "storage_disposed_date": disposal.disposal_date,
                "storage_location_id": False,
                "storage_box": False,
                "storage_slot": False,
                "storage_retrieved_date": False,
            }
        )
        self._create_storage_event(
            event_type="dispose",
            from_location=False,
            to_location=False,
            box=False,
            slot=False,
            note=note or _("Sample disposed"),
        )
        self._create_signoff("dispose", _("Sample disposed"))

    def _create_storage_event(self, event_type, from_location, to_location, box=False, slot=False, note=False):
        self.ensure_one()
        self.env["lab.sample.storage.event"].create(
            {
                "sample_id": self.id,
                "event_type": event_type,
                "event_time": fields.Datetime.now(),
                "user_id": self.env.user.id,
                "from_location_id": from_location.id if from_location else False,
                "to_location_id": to_location.id if to_location else False,
                "box": box or False,
                "slot": slot or False,
                "note": note or "-",
            }
        )

    @api.model
    def _cron_notify_storage_due(self):
        overdue_samples = self.search(
            [
                ("storage_state", "in", ("stored", "retrieved")),
                ("storage_due_date", "!=", False),
                ("storage_due_date", "<", fields.Datetime.now()),
            ]
        )
        if not overdue_samples:
            return

        manager_group = self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
        users = manager_group.user_ids if (manager_group and manager_group.user_ids) else self.env.user
        helper = self.env["lab.activity.helper.mixin"]
        entries = []

        for sample in overdue_samples:
            summary = "Storage retention overdue"
            note = (
                "Sample %s exceeded retention due date (%s). Current state: %s."
                % (sample.name, sample.storage_due_date, sample.storage_state)
            )
            for user in users:
                entries.append(
                    {
                        "res_id": sample.id,
                        "user_id": user.id,
                        "summary": summary,
                        "note": note,
                    }
                )
        helper.create_unique_todo_activities(model_name="lab.sample", entries=entries)


class LabSampleStorageEvent(models.Model):
    _name = "lab.sample.storage.event"
    _description = "Sample Storage Event"
    _order = "event_time desc, id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    event_type = fields.Selection(
        [
            ("store", "Store"),
            ("move", "Move"),
            ("retrieve", "Retrieve"),
            ("return", "Return"),
            ("dispose", "Dispose"),
            ("audit", "Audit"),
        ],
        required=True,
    )
    event_time = fields.Datetime(required=True)
    user_id = fields.Many2one("res.users", required=True)
    from_location_id = fields.Many2one("lab.storage.location", string="From Location")
    to_location_id = fields.Many2one("lab.storage.location", string="To Location")
    box = fields.Char()
    slot = fields.Char()
    note = fields.Char(required=True)


class LabSampleDisposalRecord(models.Model):
    _name = "lab.sample.disposal.record"
    _description = "Sample Disposal Record"
    _order = "disposal_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade")
    disposal_date = fields.Datetime(required=True)
    disposed_by_id = fields.Many2one("res.users", required=True)
    method = fields.Selection(
        [
            ("incineration", "Incineration"),
            ("biohazard", "Biohazard Waste"),
            ("vendor_return", "Return to Vendor"),
            ("other", "Other"),
        ],
        required=True,
        default="biohazard",
    )
    witness_name = fields.Char()
    reason = fields.Char(required=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.sample.disposal.record") or "New"
        return super().create(vals_list)
