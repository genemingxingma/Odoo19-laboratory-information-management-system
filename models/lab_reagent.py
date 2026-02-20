from odoo import api, fields, models


class LabReagentLot(models.Model):
    _name = "lab.reagent.lot"
    _description = "Lab Reagent Lot"
    _order = "expiry_date, id"

    name = fields.Char(required=True)
    service_id = fields.Many2one("lab.service", required=True)
    lot_number = fields.Char(required=True)
    vendor = fields.Char()
    received_date = fields.Date()
    opened_date = fields.Date()
    expiry_date = fields.Date(required=True)
    active = fields.Boolean(default=True)
    note = fields.Text()
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
                "Lot %s (%s) for %s expires on %s."
                % (lot.lot_number, lot.name, lot.service_id.name, lot.expiry_date)
            )
            for user in users:
                entries.append({"res_id": lot.id, "user_id": user.id, "summary": summary, "note": note})
        helper.create_unique_todo_activities(model_name="lab.reagent.lot", entries=entries)
