from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ProductTemplateLabEcommerce(models.Model):
    _inherit = "product.template"

    is_lab_test_product = fields.Boolean(string="Medical Test Product", default=False)
    lab_sale_target = fields.Selection(
        [("individual", "Individual"), ("professional", "Professional"), ("both", "Both")],
        default="both",
        string="Sale Target",
        help="Individual: online direct customer. Professional: institution/hospital/doctor portal. Both: all channels.",
    )
    lab_service_id = fields.Many2one("lab.service", string="Mapped Lab Service")
    lab_profile_id = fields.Many2one("lab.profile", string="Mapped Lab Profile")
    lab_default_priority = fields.Selection(
        selection=lambda self: self.env["lab.master.data.mixin"]._selection_priority(),
        default=lambda self: self.env["lab.master.data.mixin"]._default_priority_code(),
        string="Default Lab Priority",
    )
    lab_turnaround_note = fields.Char(string="Turnaround Note")
    lab_package_enabled = fields.Boolean(
        string="Enable Package Mapping",
        help="If enabled, one ecommerce product can expand into multiple request lines (services/profiles).",
    )
    lab_package_line_ids = fields.One2many(
        "lab.ecommerce.package.line",
        "product_tmpl_id",
        string="Package Mapping Lines",
    )
    lab_package_price_strategy = fields.Selection(
        [("proportional", "Proportional to Catalog Price"), ("equal", "Equal Split"), ("zero", "Zero Amount")],
        default="proportional",
        string="Package Pricing Strategy",
        help="How sales line amount is distributed to generated request lines for package products.",
    )

    @api.onchange("lab_service_id")
    def _onchange_lab_service_id(self):
        for rec in self:
            if rec.lab_service_id:
                rec.list_price = rec.lab_service_id.list_price

    @api.constrains("is_lab_test_product", "lab_service_id", "lab_profile_id")
    def _check_lab_mapping(self):
        for rec in self:
            if not rec.is_lab_test_product:
                continue
            if rec.lab_package_enabled and not rec.lab_package_line_ids:
                raise ValidationError(_("Package mapping is enabled but no package lines are configured."))
            if not rec.lab_package_enabled and not rec.lab_service_id and not rec.lab_profile_id:
                raise ValidationError(_("Medical test product must map to at least one lab service or profile."))


class LabEcommercePackageLine(models.Model):
    _name = "lab.ecommerce.package.line"
    _description = "Lab Ecommerce Package Line"
    _order = "sequence, id"

    product_tmpl_id = fields.Many2one("product.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    line_type = fields.Selection([("service", "Service"), ("profile", "Profile")], default="service", required=True)
    service_id = fields.Many2one("lab.service", string="Service")
    profile_id = fields.Many2one("lab.profile", string="Profile")
    quantity = fields.Integer(default=1, required=True)
    price_weight = fields.Float(
        default=1.0,
        help="Optional custom weight for proportional price allocation. If set <= 0, catalog value is used.",
    )
    note = fields.Char()

    @api.constrains("line_type", "service_id", "profile_id", "quantity")
    def _check_line(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("Package line quantity must be greater than 0."))
            if rec.line_type == "service" and not rec.service_id:
                raise ValidationError(_("Service package line requires a service."))
            if rec.line_type == "profile" and not rec.profile_id:
                raise ValidationError(_("Profile package line requires a profile."))


class ProductProductLabEcommerce(models.Model):
    _inherit = "product.product"

    is_lab_test_product = fields.Boolean(related="product_tmpl_id.is_lab_test_product", store=True, readonly=True)
    lab_sale_target = fields.Selection(related="product_tmpl_id.lab_sale_target", store=True, readonly=True)
    lab_service_id = fields.Many2one(related="product_tmpl_id.lab_service_id", store=True, readonly=True)
    lab_profile_id = fields.Many2one(related="product_tmpl_id.lab_profile_id", store=True, readonly=True)


class SaleOrderLineLabEcommerce(models.Model):
    _inherit = "sale.order.line"

    is_lab_test_line = fields.Boolean(compute="_compute_is_lab_test_line", store=True)
    lab_service_id = fields.Many2one(compute="_compute_lab_mapping", store=True, comodel_name="lab.service")
    lab_profile_id = fields.Many2one(compute="_compute_lab_mapping", store=True, comodel_name="lab.profile")

    @api.depends("product_id", "product_template_id.is_lab_test_product")
    def _compute_is_lab_test_line(self):
        for line in self:
            line.is_lab_test_line = bool(line.product_template_id.is_lab_test_product)

    @api.depends("product_id", "product_template_id.lab_service_id", "product_template_id.lab_profile_id")
    def _compute_lab_mapping(self):
        for line in self:
            line.lab_service_id = line.product_template_id.lab_service_id
            line.lab_profile_id = line.product_template_id.lab_profile_id


class SaleOrderLabEcommerce(models.Model):
    _inherit = "sale.order"

    lab_request_ids = fields.One2many("lab.test.request", "sale_order_id", string="Lab Requests", readonly=True)
    lab_request_count = fields.Integer(compute="_compute_lab_request_count")
    lab_purchase_type = fields.Selection(
        [("individual", "Individual"), ("professional", "Professional")],
        compute="_compute_lab_purchase_type",
    )

    def _compute_lab_request_count(self):
        for order in self:
            order.lab_request_count = len(order.lab_request_ids)

    def _compute_lab_purchase_type(self):
        for order in self:
            order.lab_purchase_type = "professional" if order.partner_id.is_company else "individual"

    def action_view_lab_requests(self):
        self.ensure_one()
        return {
            "name": _("Lab Requests"),
            "type": "ir.actions.act_window",
            "res_model": "lab.test.request",
            "view_mode": "list,form",
            "domain": [("sale_order_id", "=", self.id)],
            "context": {"default_sale_order_id": self.id},
        }

    @api.model
    def _get_lab_ecommerce_request_flow(self):
        """Control how far lab requests move automatically after SO confirmation."""
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("laboratory_management.ecommerce_request_flow", default="approved")
            or "approved"
        ).strip()
        allowed = {"draft", "submitted", "quoted", "approved", "in_progress"}
        return value if value in allowed else "approved"

    @api.model
    def _get_lab_ecommerce_split_requests(self):
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("laboratory_management.ecommerce_split_requests", default="0")
            or "0"
        ).strip()
        return value in ("1", "true", "True")

    @api.model
    def _estimate_package_component_catalog_value(self, package_line):
        if package_line.price_weight and package_line.price_weight > 0:
            return package_line.price_weight
        if package_line.line_type == "service" and package_line.service_id:
            return package_line.service_id.list_price or 0.0
        if package_line.line_type == "profile" and package_line.profile_id:
            return sum(package_line.profile_id.line_ids.mapped("service_id.list_price"))
        return 0.0

    @api.model
    def _prepare_lab_request_line_payloads(self, so_line):
        note = _("From SO %(order)s line %(line)s") % {"order": so_line.order_id.name, "line": so_line.sequence}
        template = so_line.product_template_id
        if template.lab_package_enabled and template.lab_package_line_ids:
            payloads = []
            package_lines = template.lab_package_line_ids.sorted("sequence")
            per_order_unit_price = so_line.price_unit or 0.0
            strategy = template.lab_package_price_strategy or "proportional"
            base_values = []
            for pkg in package_lines:
                unit_qty = max(pkg.quantity, 1)
                if strategy == "zero":
                    base = 0.0
                elif strategy == "equal":
                    base = 1.0
                else:
                    base = max(self._estimate_package_component_catalog_value(pkg), 0.0)
                base_values.append(base * unit_qty)
            total_base = sum(base_values) or float(len(package_lines) or 1)

            for index, pkg in enumerate(package_lines):
                qty = int(max(so_line.product_uom_qty, 1) * max(pkg.quantity, 1))
                per_unit_allocated_total = 0.0
                if strategy != "zero":
                    per_unit_allocated_total = per_order_unit_price * ((base_values[index] or 0.0) / total_base)
                alloc_unit_price = per_unit_allocated_total / max(pkg.quantity, 1)
                if pkg.line_type == "service" and pkg.service_id:
                    payloads.append(
                        {
                            "line_type": "service",
                            "service_id": pkg.service_id.id,
                            "specimen_sample_type": pkg.service_id.sample_type or self.env["lab.master.data.mixin"]._default_sample_type_code(),
                            "quantity": qty,
                            "unit_price": alloc_unit_price,
                            "discount_percent": so_line.discount,
                            "note": pkg.note or note,
                        }
                    )
                elif pkg.line_type == "profile" and pkg.profile_id:
                    payloads.append(
                        {
                            "line_type": "profile",
                            "profile_id": pkg.profile_id.id,
                            "specimen_sample_type": getattr(pkg.profile_id, "sample_type", False)
                            or self.env["lab.master.data.mixin"]._default_sample_type_code(),
                            "quantity": qty,
                            "unit_price": alloc_unit_price,
                            "discount_percent": so_line.discount,
                            "note": pkg.note or note,
                        }
                    )
            return payloads

        if so_line.lab_service_id:
            return [
                {
                    "line_type": "service",
                    "service_id": so_line.lab_service_id.id,
                    "specimen_sample_type": so_line.lab_service_id.sample_type
                    or self.env["lab.master.data.mixin"]._default_sample_type_code(),
                    "quantity": int(so_line.product_uom_qty),
                    "unit_price": so_line.price_unit,
                    "discount_percent": so_line.discount,
                    "note": note,
                }
            ]
        if so_line.lab_profile_id:
            return [
                {
                    "line_type": "profile",
                    "profile_id": so_line.lab_profile_id.id,
                    "specimen_sample_type": getattr(so_line.lab_profile_id, "sample_type", False)
                    or self.env["lab.master.data.mixin"]._default_sample_type_code(),
                    "quantity": int(so_line.product_uom_qty),
                    "unit_price": so_line.price_unit,
                    "discount_percent": so_line.discount,
                    "note": note,
                }
            ]
        return []

    def _prepare_lab_request_values(self, lab_lines):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        is_professional = bool(partner.is_company)

        default_priority = "routine"
        for line in lab_lines:
            priority = line.product_template_id.lab_default_priority
            if priority:
                default_priority = priority

        line_vals = []
        for so_line in lab_lines:
            payloads = self._prepare_lab_request_line_payloads(so_line)
            for payload in payloads:
                line_vals.append((0, 0, payload))

        if not line_vals:
            return {}

        return {
            "requester_partner_id": partner.id,
            "request_type": "institution" if is_professional else "individual",
            "client_partner_id": partner.id if is_professional else False,
            "patient_id": partner.id if not is_professional else False,
            "patient_name": False if not is_professional else _("To be assigned by institution"),
            "patient_phone": partner.phone,
            "priority": default_priority,
            "clinical_note": _("Auto-created from Sale Order %(name)s") % {"name": self.name},
            "sale_order_id": self.id,
            "line_ids": line_vals,
        }

    def _apply_lab_request_auto_flow(self, request):
        self.ensure_one()
        target_flow = self._get_lab_ecommerce_request_flow()
        try:
            if target_flow in ("submitted", "quoted", "approved", "in_progress"):
                request.action_submit()
            if target_flow in ("quoted", "approved", "in_progress"):
                request.action_prepare_quote()
            if target_flow in ("approved", "in_progress"):
                request.action_approve_quote()
            if target_flow == "in_progress":
                request.action_create_samples()
        except UserError as exc:
            body = _(
                "Lab request %(request)s auto-flow stopped at policy step (%(flow)s): %(error)s"
            ) % {"request": request.name, "flow": target_flow, "error": str(exc)}
            self.message_post(body=body, subtype_xmlid="mail.mt_note")
            request.message_post(body=body, subtype_xmlid="mail.mt_note")
        return request

    def _create_lab_request_records(self, lab_lines):
        request_model = self.env["lab.test.request"]
        for order in self:
            if order.lab_request_ids:
                continue
            split = order._get_lab_ecommerce_split_requests()
            line_groups = [[line] for line in lab_lines] if split else [lab_lines]
            for line_group in line_groups:
                request_vals = order._prepare_lab_request_values(line_group)
                if not request_vals:
                    continue
                request = request_model.create(request_vals)
                order._apply_lab_request_auto_flow(request)
                request.message_post(
                    body=_("Linked with sale order <b>%(order)s</b>.") % {"order": order.name},
                    subtype_xmlid="mail.mt_note",
                )
                order.message_post(
                    body=_("Auto-created lab request <b>%(request)s</b>.") % {"request": request.name},
                    subtype_xmlid="mail.mt_note",
                )

    def _create_lab_request_from_order(self):
        for order in self:
            if order.lab_request_ids:
                continue
            lab_lines = order.order_line.filtered(lambda l: l.is_lab_test_line)
            if not lab_lines:
                continue
            order._create_lab_request_records(lab_lines)

    def action_confirm(self):
        res = super().action_confirm()
        self._create_lab_request_from_order()
        return res

    def action_sync_lab_requests(self):
        """Manual utility for existing confirmed SOs when products or policies changed."""
        for order in self:
            if order.state not in ("sale", "done"):
                continue
            lab_lines = order.order_line.filtered(lambda l: l.is_lab_test_line)
            if not lab_lines:
                continue
            order._create_lab_request_records(lab_lines)
        return True


class LabTestRequestSaleLink(models.Model):
    _inherit = "lab.test.request"

    sale_order_id = fields.Many2one("sale.order", string="Source Sale Order", readonly=True, copy=False)


class WebsiteSaleProfessionalGuard(models.Model):
    _inherit = "sale.order"

    def _cart_update(self, product_id=None, line_id=None, add_qty=0, set_qty=0, **kwargs):
        """Block adding professional-only medical test products in public/individual storefront carts."""
        if product_id:
            product = self.env["product.product"].browse(product_id)
            if product.exists() and product.is_lab_test_product and product.lab_sale_target == "professional":
                user_partner = self.env.user.partner_id.commercial_partner_id
                if not user_partner.is_company:
                    raise UserError(
                        _("This medical test service is for professional customers (institution/hospital/doctor portal).")
                    )
        return super()._cart_update(product_id=product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, **kwargs)
