from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabAssayKit(models.Model):
    _name = "lab.assay.kit"
    _description = "Lab Assay Kit"
    _order = "name"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    vendor = fields.Char()
    manufacturer = fields.Char()
    method = fields.Selection(
        [
            ("pcr", "PCR"),
            ("qpcr", "qPCR"),
            ("multiplex_pcr", "Multiplex PCR"),
            ("other", "Other"),
        ],
        default="multiplex_pcr",
        required=True,
    )
    covered_service_ids = fields.Many2many("lab.service", string="Covered Services", required=True)
    default_reactions_per_kit = fields.Float(default=96.0)
    active = fields.Boolean(default=True)
    note = fields.Text()

    _kit_code_uniq = models.Constraint("unique(code)", "Assay kit code must be unique.")

    @api.constrains("covered_service_ids")
    def _check_covered_services(self):
        for rec in self:
            if not rec.covered_service_ids:
                raise ValidationError(_("Assay kit must cover at least one service."))

    def name_get(self):
        return [(rec.id, "%s [%s]" % (rec.name, rec.code)) for rec in self]


class LabReagentLot(models.Model):
    _name = "lab.reagent.lot"
    _description = "Lab Reagent Lot"
    _order = "expiry_date, id"

    name = fields.Char(required=True)
    reagent_scope = fields.Selection(
        [("single", "Single Service"), ("panel", "Multiplex Panel")],
        default="single",
        required=True,
    )
    service_id = fields.Many2one("lab.service")
    assay_kit_id = fields.Many2one("lab.assay.kit", string="Assay Kit")
    covered_service_ids = fields.Many2many(
        "lab.service",
        compute="_compute_covered_service_ids",
        string="Covered Services",
        store=False,
    )
    lot_number = fields.Char(required=True)
    vendor = fields.Char()
    received_date = fields.Date()
    opened_date = fields.Date()
    expiry_date = fields.Date(required=True)
    reactions_total = fields.Float(default=0.0, help="Planned total reaction capacity for this lot.")
    reactions_used = fields.Float(compute="_compute_usage", store=True)
    reactions_remaining = fields.Float(compute="_compute_usage", store=True)
    active = fields.Boolean(default=True)
    note = fields.Text()
    usage_line_ids = fields.One2many("lab.reagent.usage", "reagent_lot_id", string="Usage Lines", readonly=True)
    is_expired = fields.Boolean(compute="_compute_is_expired", search="_search_is_expired", store=False)
    days_to_expiry = fields.Integer(compute="_compute_is_expired", store=False)
    is_expiring_soon = fields.Boolean(compute="_compute_is_expired", search="_search_is_expiring_soon", store=False)

    @api.depends("expiry_date")
    def _compute_is_expired(self):
        today = fields.Date.today()
        for rec in self:
            if rec.expiry_date:
                rec.days_to_expiry = (rec.expiry_date - today).days
                rec.is_expired = rec.days_to_expiry < 0
                rec.is_expiring_soon = 0 <= rec.days_to_expiry <= 7
            else:
                rec.days_to_expiry = 0
                rec.is_expired = False
                rec.is_expiring_soon = False

    @api.depends("usage_line_ids.quantity", "usage_line_ids.state", "reactions_total")
    def _compute_usage(self):
        for rec in self:
            used = sum(rec.usage_line_ids.filtered(lambda x: x.state == "posted").mapped("quantity"))
            rec.reactions_used = used
            rec.reactions_remaining = (rec.reactions_total or 0.0) - used

    @api.depends("reagent_scope", "service_id", "assay_kit_id", "assay_kit_id.covered_service_ids")
    def _compute_covered_service_ids(self):
        for rec in self:
            if rec.reagent_scope == "single" and rec.service_id:
                rec.covered_service_ids = rec.service_id
            else:
                rec.covered_service_ids = rec.assay_kit_id.covered_service_ids

    @api.onchange("assay_kit_id", "reagent_scope")
    def _onchange_assay_kit(self):
        for rec in self:
            if rec.reagent_scope == "panel" and rec.assay_kit_id and not rec.reactions_total:
                rec.reactions_total = rec.assay_kit_id.default_reactions_per_kit

    @api.constrains("reagent_scope", "service_id", "assay_kit_id")
    def _check_scope_binding(self):
        for rec in self:
            if rec.reagent_scope == "single":
                if not rec.service_id:
                    raise ValidationError(_("Single-service lot requires service."))
                if rec.assay_kit_id:
                    raise ValidationError(_("Single-service lot cannot bind an assay kit."))
            else:
                if not rec.assay_kit_id:
                    raise ValidationError(_("Panel lot requires assay kit."))
                if rec.service_id:
                    raise ValidationError(_("Panel lot should not bind single service."))

    @api.constrains("reactions_total")
    def _check_reaction_total(self):
        for rec in self:
            if rec.reactions_total < 0:
                raise ValidationError(_("Reaction total cannot be negative."))

    def _can_cover_service(self, service):
        self.ensure_one()
        if self.reagent_scope == "single":
            return self.service_id == service
        return service in self.assay_kit_id.covered_service_ids

    def _consume(self, quantity, sample=False, analysis=False, note=False):
        self.ensure_one()
        if quantity <= 0:
            return False
        if self.reactions_total and self.reactions_remaining < quantity - 0.00001:
            raise ValidationError(
                _("Lot %s does not have enough reactions remaining (remaining %.2f, requested %.2f).")
                % (self.display_name, self.reactions_remaining, quantity)
            )
        return self.env["lab.reagent.usage"].create(
            {
                "reagent_lot_id": self.id,
                "sample_id": sample.id if sample else False,
                "analysis_id": analysis.id if analysis else False,
                "quantity": quantity,
                "note": note or False,
                "state": "posted",
            }
        )

    def _search_is_expiring_soon(self, operator, value):
        today = fields.Date.today()
        threshold = fields.Date.add(today, days=7)
        soon_domain = [
            ("expiry_date", "!=", False),
            ("expiry_date", ">=", today),
            ("expiry_date", "<=", threshold),
            ("active", "=", True),
        ]
        not_soon_domain = [
            "|",
            ("expiry_date", "=", False),
            "|",
            ("expiry_date", "<", today),
            ("expiry_date", ">", threshold),
        ]
        if operator in ("=", "=="):
            return soon_domain if value else not_soon_domain
        if operator == "!=":
            return not_soon_domain if value else soon_domain
        return soon_domain

    def _search_is_expired(self, operator, value):
        today = fields.Date.today()
        expired_domain = [
            ("expiry_date", "!=", False),
            ("expiry_date", "<", today),
        ]
        not_expired_domain = [
            "|",
            ("expiry_date", "=", False),
            ("expiry_date", ">=", today),
        ]
        if operator in ("=", "=="):
            return expired_domain if value else not_expired_domain
        if operator == "!=":
            return not_expired_domain if value else expired_domain
        return expired_domain

    @api.model
    def _cron_notify_expiring_lots(self):
        """Notify managers for lots expiring in next 7 days."""
        today = fields.Date.today()
        threshold = fields.Date.add(today, days=7)
        lots = self.search(
            [
                ("active", "=", True),
                ("expiry_date", "!=", False),
                ("expiry_date", ">=", today),
                ("expiry_date", "<=", threshold),
            ]
        )
        if not lots:
            return

        manager_group = self.env.ref("laboratory_management.group_lab_manager", raise_if_not_found=False)
        users = manager_group.user_ids if (manager_group and manager_group.user_ids) else self.env.user
        helper = self.env["lab.activity.helper.mixin"]
        entries = []

        for lot in lots:
            summary = "Reagent lot expiring soon"
            note = (
                "Lot %s (%s) expires on %s."
                % (lot.lot_number, lot.name, lot.expiry_date)
            )
            for user in users:
                entries.append({"res_id": lot.id, "user_id": user.id, "summary": summary, "note": note})
        helper.create_unique_todo_activities(model_name="lab.reagent.lot", entries=entries)


class LabReagentUsage(models.Model):
    _name = "lab.reagent.usage"
    _description = "Lab Reagent Usage"
    _order = "id desc"

    reagent_lot_id = fields.Many2one("lab.reagent.lot", required=True, ondelete="cascade", index=True)
    sample_id = fields.Many2one("lab.sample", index=True)
    analysis_id = fields.Many2one("lab.sample.analysis", index=True)
    quantity = fields.Float(required=True, default=1.0)
    usage_time = fields.Datetime(default=fields.Datetime.now, required=True)
    state = fields.Selection([("draft", "Draft"), ("posted", "Posted"), ("cancelled", "Cancelled")], default="posted")
    note = fields.Char()

    @api.constrains("quantity")
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("Usage quantity must be greater than 0."))

    _uniq_analysis_usage = models.Constraint(
        "unique(reagent_lot_id, analysis_id)",
        "A lot usage record already exists for this analysis.",
    )
