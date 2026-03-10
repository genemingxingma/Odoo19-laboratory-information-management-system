from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabQcMaterialBatchWizard(models.TransientModel):
    _name = "lab.qc.material.batch.wizard"
    _description = "QC Material Batch Create Wizard"

    create_mode = fields.Selection(
        [("service", "By Services"), ("panel", "By Panels"), ("both", "Services + Panels")],
        string="Creation Mode",
        default="both",
        required=True,
    )
    service_ids = fields.Many2many(
        "lab.service",
        "lab_qc_batch_wizard_service_rel",
        "wizard_id",
        "service_id",
        string="Services",
        domain="[('active','=',True)]",
    )
    panel_ids = fields.Many2many(
        "lab.profile",
        "lab_qc_batch_wizard_panel_rel",
        "wizard_id",
        "panel_id",
        string="Panels",
        domain="[('active','=',True)]",
    )
    name_template = fields.Char(
        string="Material Name Prefix",
        required=True,
        default="QC Material",
        help="Final material name will be: <prefix> - <service name>.",
    )
    code_prefix = fields.Char(
        string="Code Prefix",
        required=True,
        default="QC",
        help="Final code will be: <prefix>-<service code>.",
    )
    lot_number = fields.Char(required=True)
    target_value = fields.Float(required=True)
    std_dev = fields.Float(required=True, default=1.0)
    rule_ids = fields.Many2many(
        "lab.qc.rule.library",
        "lab_qc_batch_wizard_rule_rel",
        "wizard_id",
        "rule_id",
        string="Westgard Rules",
        domain=[("active", "=", True)],
        help="If left empty, each material uses all active rules from the rule library.",
    )
    note = fields.Text()
    skip_existing = fields.Boolean(
        string="Skip Existing (Same Service + Lot)",
        default=True,
        help="If enabled, materials with the same service and lot number are not created again.",
    )
    service_count = fields.Integer(compute="_compute_service_count")

    @api.depends("create_mode", "service_ids", "panel_ids", "panel_ids.line_ids", "panel_ids.line_ids.service_id")
    def _compute_service_count(self):
        for rec in self:
            rec.service_count = len(rec._get_target_services())

    def _get_target_services(self):
        self.ensure_one()
        service_set = self.env["lab.service"]

        include_services = self.create_mode in ("service", "both")
        include_panels = self.create_mode in ("panel", "both")

        if include_services and self.service_ids:
            service_set |= self.service_ids
        if include_panels and self.panel_ids:
            service_set |= self.panel_ids.mapped("line_ids.service_id")
        return service_set.filtered("active")

    @api.constrains("std_dev")
    def _check_std_dev(self):
        for rec in self:
            if rec.std_dev <= 0:
                raise ValidationError(_("Standard deviation must be greater than zero."))

    def action_batch_create(self):
        self.ensure_one()
        services = self._get_target_services()
        if not services:
            raise UserError(_("Please select at least one service directly or through selected panels."))

        qc_material_obj = self.env["lab.qc.material"]
        created = self.env["lab.qc.material"]
        skipped = 0

        for service in services:
            if self.skip_existing:
                exists = qc_material_obj.search_count(
                    [
                        ("service_id", "=", service.id),
                        ("lot_number", "=", self.lot_number),
                    ]
                )
                if exists:
                    skipped += 1
                    continue

            material_vals = {
                "name": "%s - %s" % (self.name_template, service.name),
                "code": "%s-%s" % (self.code_prefix, service.code),
                "service_id": service.id,
                "lot_number": self.lot_number,
                "target_value": self.target_value,
                "std_dev": self.std_dev,
                "note": self.note,
            }
            material = qc_material_obj.create(material_vals)
            if self.rule_ids:
                material.rule_ids = [(6, 0, self.rule_ids.ids)]
            created |= material

        message = _(
            "QC material batch creation completed. Created: %(created)s, Skipped: %(skipped)s, Total target services: %(total)s."
        ) % {"created": len(created), "skipped": skipped, "total": len(services)}

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("QC Materials"),
                "message": message,
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "name": _("QC Materials"),
                    "res_model": "lab.qc.material",
                    "view_mode": "list,form",
                    "domain": [("id", "in", created.ids)] if created else [],
                },
            },
        }
