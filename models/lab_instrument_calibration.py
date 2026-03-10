from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabInstrument(models.Model):
    _inherit = "lab.instrument"

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True, index=True)
    equipment_id = fields.Many2one("maintenance.equipment", string="Maintenance Equipment")
    responsible_user_id = fields.Many2one("res.users", string="Instrument Owner", default=lambda self: self.env.user)
    quality_owner_id = fields.Many2one("res.users", string="Quality Owner")
    calibration_policy = fields.Selection(
        [
            ("none", "No Scheduled Calibration"),
            ("internal", "Internal Calibration"),
            ("external", "External Calibration"),
            ("vendor", "Vendor Calibration"),
        ],
        default="internal",
        required=True,
    )
    calibration_interval_days = fields.Integer(default=180)
    calibration_warning_days = fields.Integer(default=14)
    calibration_grace_days = fields.Integer(default=0)
    block_run_if_calibration_overdue = fields.Boolean(default=True)
    last_calibration_date = fields.Date()
    next_calibration_date = fields.Date(compute="_compute_calibration_status", store=True)
    calibration_status = fields.Selection(
        [("none", "Not Applicable"), ("valid", "Valid"), ("due", "Due Soon"), ("overdue", "Overdue")],
        compute="_compute_calibration_status",
        store=True,
    )
    calibration_note = fields.Text()
    calibration_record_ids = fields.One2many("lab.instrument.calibration", "instrument_id", string="Calibration Records")
    calibration_record_count = fields.Integer(compute="_compute_calibration_record_count")
    equipment_serial_no = fields.Char(related="equipment_id.serial_no", readonly=True)
    equipment_model = fields.Char(related="equipment_id.model", readonly=True)

    _equipment_uniq = models.Constraint(
        "unique(equipment_id)",
        "A maintenance equipment record can only be linked to one laboratory instrument.",
    )

    @api.depends(
        "calibration_policy",
        "calibration_interval_days",
        "calibration_warning_days",
        "last_calibration_date",
        "calibration_record_ids.state",
        "calibration_record_ids.result",
        "calibration_record_ids.performed_date",
    )
    def _compute_calibration_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            passed = rec.calibration_record_ids.filtered(lambda x: x.state == "completed" and x.result == "pass" and x.performed_date)
            latest = passed.sorted(lambda x: x.performed_date)[-1:] if passed else self.env["lab.instrument.calibration"]
            base_date = latest.performed_date if latest else rec.last_calibration_date
            if rec.calibration_policy == "none" or not rec.calibration_interval_days:
                rec.next_calibration_date = False
                rec.calibration_status = "none"
                continue
            rec.next_calibration_date = fields.Date.add(base_date or today, days=rec.calibration_interval_days) if base_date else False
            if not rec.next_calibration_date:
                rec.calibration_status = "due"
                continue
            warn_date = fields.Date.add(rec.next_calibration_date, days=-(rec.calibration_warning_days or 0))
            overdue_date = fields.Date.add(rec.next_calibration_date, days=rec.calibration_grace_days or 0)
            if today > overdue_date:
                rec.calibration_status = "overdue"
            elif today >= warn_date:
                rec.calibration_status = "due"
            else:
                rec.calibration_status = "valid"

    def _compute_calibration_record_count(self):
        for rec in self:
            rec.calibration_record_count = len(rec.calibration_record_ids)

    @api.constrains("calibration_interval_days", "calibration_warning_days", "calibration_grace_days")
    def _check_calibration_numbers(self):
        for rec in self:
            if rec.calibration_interval_days < 0 or rec.calibration_warning_days < 0 or rec.calibration_grace_days < 0:
                raise ValidationError(_("Calibration interval, warning days, and grace days must be zero or positive."))

    def action_view_calibration_records(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_instrument_calibration").sudo().read()[0]
        action["domain"] = [("instrument_id", "=", self.id)]
        action["context"] = {"default_instrument_id": self.id, "default_equipment_id": self.equipment_id.id}
        return action

    def action_create_calibration_record(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("New Calibration Record"),
            "res_model": "lab.instrument.calibration",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_instrument_id": self.id,
                "default_equipment_id": self.equipment_id.id,
                "default_planned_date": self.next_calibration_date or fields.Date.context_today(self),
            },
        }

    @api.onchange("equipment_id")
    def _onchange_equipment_id_sync_identity(self):
        for rec in self:
            if not rec.equipment_id:
                continue
            rec.name = rec.equipment_id.name
            rec.code = rec.equipment_id.serial_no or rec.equipment_id.name
            if hasattr(rec.equipment_id, "owner_user_id") and rec.equipment_id.owner_user_id:
                rec.responsible_user_id = rec.equipment_id.owner_user_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            equipment_id = vals.get("equipment_id")
            if equipment_id:
                equipment = self.env["maintenance.equipment"].browse(equipment_id)
                vals.setdefault("name", equipment.name)
                vals.setdefault("code", equipment.serial_no or equipment.name)
                vals.setdefault("company_id", equipment.company_id.id or self.env.company.id)
                if getattr(equipment, "owner_user_id", False):
                    vals.setdefault("responsible_user_id", equipment.owner_user_id.id)
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("equipment_id"):
            equipment = self.env["maintenance.equipment"].browse(vals["equipment_id"])
            vals.setdefault("name", equipment.name)
            vals.setdefault("code", equipment.serial_no or equipment.name)
            vals.setdefault("company_id", equipment.company_id.id or self.env.company.id)
            if getattr(equipment, "owner_user_id", False):
                vals.setdefault("responsible_user_id", equipment.owner_user_id.id)
        return super().write(vals)

    def _cron_notify_calibration_due(self):
        helper = self.env["lab.activity.helper.mixin"]
        target_instruments = self.search(
            [
                ("calibration_policy", "!=", "none"),
                ("calibration_status", "in", ("due", "overdue")),
                ("active", "=", True),
            ]
        )
        entries = []
        for rec in target_instruments:
            user = rec.quality_owner_id or rec.responsible_user_id
            if not user:
                continue
            summary = _("Instrument calibration overdue") if rec.calibration_status == "overdue" else _("Instrument calibration due soon")
            note = _(
                "Instrument %(instrument)s calibration status is %(status)s. Next calibration date: %(date)s."
            ) % {
                "instrument": rec.display_name,
                "status": dict(self._fields["calibration_status"].selection).get(rec.calibration_status, rec.calibration_status),
                "date": rec.next_calibration_date or "-",
            }
            entries.append({"res_id": rec.id, "user_id": user.id, "summary": summary, "note": note})
        helper.create_unique_todo_activities(model_name=self._name, entries=entries)


class LabInstrumentCalibration(models.Model):
    _name = "lab.instrument.calibration"
    _description = "Laboratory Instrument Calibration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "planned_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    instrument_id = fields.Many2one("lab.instrument", required=True, ondelete="cascade", tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    equipment_id = fields.Many2one("maintenance.equipment", string="Maintenance Equipment", tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("planned", "Planned"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    calibration_type_id = fields.Many2one(
        "lab.calibration.type",
        string="Calibration Type",
        required=True,
        default=lambda self: self.env["lab.master.data.mixin"]._default_calibration_type_id(),
        tracking=True,
    )
    calibration_type = fields.Char(compute="_compute_legacy_labels", string="Calibration Type (Legacy)")
    planned_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    performed_date = fields.Date(tracking=True)
    next_due_date = fields.Date(compute="_compute_next_due_date", store=True)
    performed_by_id = fields.Many2one("res.users", string="Performed By", default=lambda self: self.env.user, tracking=True)
    vendor_partner_id = fields.Many2one("res.partner", string="Vendor", tracking=True)
    certificate_reference = fields.Char(tracking=True)
    result = fields.Selection([("pass", "Pass"), ("fail", "Fail"), ("na", "Not Applicable")], default="pass", tracking=True)
    note = fields.Text()
    maintenance_request_id = fields.Many2one("maintenance.request", string="Maintenance Request", tracking=True)
    attachment_count = fields.Integer(compute="_compute_attachment_count")
    is_overdue = fields.Boolean(compute="_compute_is_overdue", search="_search_is_overdue")

    _sql_constraints = [
        ("lab_instrument_calibration_name_uniq", "unique(name)", "Calibration record number must be unique."),
    ]

    @api.depends("planned_date", "instrument_id.calibration_interval_days", "performed_date", "state", "result")
    def _compute_next_due_date(self):
        for rec in self:
            base = rec.performed_date or rec.planned_date
            if rec.state == "completed" and rec.result == "pass" and base and rec.instrument_id.calibration_interval_days:
                rec.next_due_date = fields.Date.add(base, days=rec.instrument_id.calibration_interval_days)
            else:
                rec.next_due_date = False

    @api.depends("planned_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.planned_date and rec.state not in ("completed", "cancel") and rec.planned_date < today)

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        domain = [("planned_date", "<", today), ("state", "not in", ("completed", "cancel"))]
        if (operator in ("=", "==") and value) or (operator == "!=" and not value):
            return domain
        return ["!"] + domain

    def _compute_attachment_count(self):
        attachment_obj = self.env["ir.attachment"].sudo()
        for rec in self:
            rec.attachment_count = attachment_obj.search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id)])

    @api.depends("calibration_type_id")
    def _compute_legacy_labels(self):
        for rec in self:
            rec.calibration_type = rec.calibration_type_id.display_name

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.instrument.calibration") or "New"
            if not vals.get("company_id") and vals.get("instrument_id"):
                instrument = self.env["lab.instrument"].browse(vals["instrument_id"])
                vals["company_id"] = instrument.company_id.id or self.env.company.id
        return super().create(vals_list)

    @api.constrains("performed_date", "planned_date")
    def _check_dates(self):
        for rec in self:
            if rec.performed_date and rec.planned_date and rec.performed_date < rec.planned_date:
                raise ValidationError(_("Performed date cannot be earlier than planned date."))

    def action_plan(self):
        self.write({"state": "planned"})

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_complete(self):
        for rec in self:
            performed_date = rec.performed_date or fields.Date.context_today(rec)
            rec.write({"state": "completed", "performed_date": performed_date})
            if rec.result == "pass":
                rec.instrument_id.write({"last_calibration_date": performed_date})

    def action_fail(self):
        self.write({"state": "failed", "performed_date": self.performed_date or fields.Date.context_today(self), "result": "fail"})

    def action_cancel(self):
        self.write({"state": "cancel"})

    def action_view_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Calibration Evidence"),
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {
                "default_res_model": self._name,
                "default_res_id": self.id,
            },
        }


class LabInstrumentRunCalibrationGuard(models.Model):
    _inherit = "lab.instrument.run"

    instrument_calibration_status = fields.Selection(related="instrument_id.calibration_status", readonly=True)
    instrument_next_calibration_date = fields.Date(related="instrument_id.next_calibration_date", readonly=True)

    def action_start_run(self):
        for rec in self:
            instrument = rec.instrument_id
            if instrument and instrument.block_run_if_calibration_overdue and instrument.calibration_status == "overdue":
                raise UserError(
                    _(
                        "Instrument %(instrument)s calibration is overdue (next calibration date: %(date)s). Complete calibration before starting the run."
                    )
                    % {
                        "instrument": instrument.display_name,
                        "date": instrument.next_calibration_date or "-",
                    }
                )
        return super().action_start_run()


class MaintenanceEquipmentLabInstrument(models.Model):
    _inherit = "maintenance.equipment"

    lab_instrument_ids = fields.One2many("lab.instrument", "equipment_id", string="Laboratory Instruments")
    lab_instrument_count = fields.Integer(compute="_compute_lab_instrument_count")

    def _compute_lab_instrument_count(self):
        for rec in self:
            rec.lab_instrument_count = len(rec.lab_instrument_ids)

    def action_view_lab_instrument(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_instrument").sudo().read()[0]
        action["domain"] = [("equipment_id", "=", self.id)]
        action["context"] = {
            "default_equipment_id": self.id,
            "default_name": self.name,
            "default_code": self.serial_no or self.name,
            "default_responsible_user_id": self.owner_user_id.id,
            "default_company_id": self.company_id.id,
        }
        if len(self.lab_instrument_ids) == 1:
            action["view_mode"] = "form"
            action["res_id"] = self.lab_instrument_ids.id
        return action

    def action_create_lab_instrument(self):
        self.ensure_one()
        existing = self.lab_instrument_ids[:1]
        if existing:
            return existing.action_view_calibration_records() if self.env.context.get("open_calibration") else {
                "type": "ir.actions.act_window",
                "name": _("Laboratory Instrument"),
                "res_model": "lab.instrument",
                "res_id": existing.id,
                "view_mode": "form",
                "target": "current",
            }
        instrument = self.env["lab.instrument"].create(
            {
                "name": self.name,
                "code": self.serial_no or self.name,
                "company_id": self.company_id.id,
                "equipment_id": self.id,
                "responsible_user_id": self.owner_user_id.id,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Laboratory Instrument"),
            "res_model": "lab.instrument",
            "res_id": instrument.id,
            "view_mode": "form",
            "target": "current",
        }

    def write(self, vals):
        res = super().write(vals)
        sync_fields = {"name", "serial_no", "owner_user_id", "company_id"}
        if sync_fields.intersection(vals):
            for equipment in self:
                linked = equipment.lab_instrument_ids
                if not linked:
                    continue
                updates = {
                    "name": equipment.name,
                    "code": equipment.serial_no or equipment.name,
                    "company_id": equipment.company_id.id,
                }
                if equipment.owner_user_id:
                    updates["responsible_user_id"] = equipment.owner_user_id.id
                linked.write(updates)
        return res


class MaintenanceRequestCalibration(models.Model):
    _inherit = "maintenance.request"

    lab_instrument_id = fields.Many2one(
        "lab.instrument",
        string="Laboratory Instrument",
        compute="_compute_lab_instrument_id",
        store=True,
        readonly=True,
    )
    requires_recalibration = fields.Boolean(
        string="Requires Recalibration",
        help="Enable this when the maintenance work affects measurement performance and the instrument must be recalibrated before routine use.",
        tracking=True,
    )
    recalibration_type_id = fields.Many2one(
        "lab.calibration.type",
        string="Recalibration Type",
        default=lambda self: self.env["lab.calibration.type"].sudo().search([("code", "=", "post_maintenance"), ("active", "=", True)], limit=1).id
        or self.env["lab.master.data.mixin"]._default_calibration_type_id(),
        tracking=True,
    )
    recalibration_note = fields.Text(string="Recalibration Note")
    calibration_record_id = fields.Many2one(
        "lab.instrument.calibration",
        string="Calibration Record",
        readonly=True,
        copy=False,
    )

    @api.depends("equipment_id", "equipment_id.lab_instrument_ids")
    def _compute_lab_instrument_id(self):
        for rec in self:
            rec.lab_instrument_id = rec.equipment_id.lab_instrument_ids[:1]

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._trigger_recalibration_if_needed()
        return records

    def write(self, vals):
        res = super().write(vals)
        trigger_fields = {"stage_id", "requires_recalibration", "equipment_id", "done", "close_date"}
        if trigger_fields.intersection(vals):
            self._trigger_recalibration_if_needed()
        return res

    def _trigger_recalibration_if_needed(self):
        helper = self.env["lab.activity.helper.mixin"]
        today = fields.Date.context_today(self)
        activity_entries = []
        for rec in self:
            if not rec.requires_recalibration or not rec.done or not rec.lab_instrument_id or rec.calibration_record_id:
                continue
            calibration_type = rec.recalibration_type_id or self.env["lab.calibration.type"].sudo().search(
                [("code", "=", "post_maintenance"), ("active", "=", True)], limit=1
            )
            calibration = self.env["lab.instrument.calibration"].create(
                {
                    "instrument_id": rec.lab_instrument_id.id,
                    "company_id": rec.lab_instrument_id.company_id.id,
                    "equipment_id": rec.equipment_id.id,
                    "maintenance_request_id": rec.id,
                    "planned_date": today,
                    "state": "planned",
                    "calibration_type_id": calibration_type.id,
                    "note": rec.recalibration_note
                    or _("Generated from maintenance request %(request)s after work completion.") % {"request": rec.display_name},
                }
            )
            rec.calibration_record_id = calibration.id
            user = rec.lab_instrument_id.quality_owner_id or rec.lab_instrument_id.responsible_user_id
            if user:
                activity_entries.append(
                    {
                        "res_id": calibration.id,
                        "user_id": user.id,
                        "summary": _("Perform post-maintenance calibration"),
                        "note": _(
                            "Maintenance request %(request)s was completed and requires recalibration for instrument %(instrument)s."
                        )
                        % {
                            "request": rec.display_name,
                            "instrument": rec.lab_instrument_id.display_name,
                        },
                    }
                )
            rec.message_post(
                body=_("Calibration record %(record)s was created because this maintenance request requires recalibration.")
                % {"record": calibration.display_name}
            )
        if activity_entries:
            helper.create_unique_todo_activities(model_name="lab.instrument.calibration", entries=activity_entries)
