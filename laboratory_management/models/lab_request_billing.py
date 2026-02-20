from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabRequestInvoice(models.Model):
    _name = "lab.request.invoice"
    _description = "Lab Request Invoice"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade", tracking=True)
    partner_id = fields.Many2one("res.partner", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    invoice_date = fields.Date(default=fields.Date.today, required=True, tracking=True)
    due_date = fields.Date(required=True, tracking=True)
    note = fields.Text()

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("issued", "Issued"),
            ("partially_paid", "Partially Paid"),
            ("paid", "Paid"),
            ("void", "Void"),
        ],
        default="draft",
        tracking=True,
    )
    payment_state = fields.Selection(
        [("unpaid", "Unpaid"), ("partial", "Partially Paid"), ("paid", "Paid")],
        compute="_compute_amounts",
        store=True,
    )

    line_ids = fields.One2many("lab.request.invoice.line", "invoice_id", string="Invoice Lines")
    payment_ids = fields.One2many("lab.request.payment", "invoice_id", string="Payments", readonly=True)

    amount_untaxed = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_discount = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_total = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_paid = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)
    amount_residual = fields.Monetary(compute="_compute_amounts", currency_field="currency_id", store=True)

    payment_count = fields.Integer(compute="_compute_payment_count")
    portal_last_viewed_at = fields.Datetime(readonly=True)

    @api.depends("payment_ids")
    def _compute_payment_count(self):
        for rec in self:
            rec.payment_count = len(rec.payment_ids)

    @api.depends(
        "line_ids.subtotal",
        "line_ids.discount_amount",
        "payment_ids.amount",
        "payment_ids.state",
        "state",
    )
    def _compute_amounts(self):
        for rec in self:
            gross = sum(rec.line_ids.mapped("subtotal_gross"))
            discount = sum(rec.line_ids.mapped("discount_amount"))
            total = sum(rec.line_ids.mapped("subtotal"))
            paid = sum(rec.payment_ids.filtered(lambda p: p.state == "confirmed").mapped("amount"))
            residual = max(total - paid, 0.0)

            rec.amount_untaxed = gross
            rec.amount_discount = discount
            rec.amount_total = total
            rec.amount_paid = paid
            rec.amount_residual = residual

            if rec.state == "void":
                rec.payment_state = "unpaid"
            elif residual <= 0 and total > 0:
                rec.payment_state = "paid"
            elif paid > 0:
                rec.payment_state = "partial"
            else:
                rec.payment_state = "unpaid"

    @api.constrains("due_date", "invoice_date")
    def _check_due_date(self):
        for rec in self:
            if rec.due_date and rec.invoice_date and rec.due_date < rec.invoice_date:
                raise ValidationError(_("Invoice due date cannot be earlier than invoice date."))

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.request.invoice") or "New"
            if not vals.get("due_date"):
                invoice_date = vals.get("invoice_date") or fields.Date.today()
                vals["due_date"] = fields.Date.add(invoice_date, days=7)
        return super().create(vals_list)

    def action_issue(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if not rec.line_ids:
                raise UserError(_("Cannot issue an invoice without lines."))
            if rec.amount_total <= 0:
                raise UserError(_("Invoice total must be greater than 0 before issue."))
            rec.state = "issued"
            rec.message_post(
                body=_("Invoice %(invoice)s issued with amount %(amount).2f")
                % {"invoice": rec.name, "amount": rec.amount_total},
                subtype_xmlid="mail.mt_note",
            )

    def action_mark_void(self):
        for rec in self:
            if rec.payment_ids.filtered(lambda p: p.state == "confirmed"):
                raise UserError(_("Cannot void invoice with confirmed payments."))
            rec.state = "void"
            rec.message_post(body=_("Invoice voided."), subtype_xmlid="mail.mt_note")

    def action_reset_draft(self):
        for rec in self:
            if rec.state == "paid":
                raise UserError(_("Paid invoice cannot be reset to draft."))
            rec.state = "draft"

    def action_mark_paid(self):
        for rec in self:
            if rec.state not in ("issued", "partially_paid"):
                raise UserError(_("Only issued invoices can be marked paid."))
            if rec.amount_residual > 0:
                raise UserError(_("Cannot mark paid while residual amount exists."))
            rec.state = "paid"

    def action_view_payments(self):
        self.ensure_one()
        return {
            "name": _("Payments"),
            "type": "ir.actions.act_window",
            "res_model": "lab.request.payment",
            "view_mode": "list,form",
            "domain": [("invoice_id", "=", self.id)],
            "context": {"default_invoice_id": self.id},
        }

    def action_register_payment(self):
        self.ensure_one()
        if self.state not in ("issued", "partially_paid"):
            raise UserError(_("Payment can only be registered on issued invoices."))
        return {
            "name": _("Register Payment"),
            "type": "ir.actions.act_window",
            "res_model": "lab.request.payment",
            "view_mode": "form",
            "target": "current",
            "context": {
                "default_invoice_id": self.id,
                "default_request_id": self.request_id.id,
                "default_payer_partner_id": self.partner_id.id,
                "default_amount": self.amount_residual,
            },
        }

    @api.model
    def _cron_unpaid_invoice_followup(self):
        today = fields.Date.today()
        overdue = self.search(
            [
                ("state", "in", ("issued", "partially_paid")),
                ("due_date", "!=", False),
                ("due_date", "<", today),
            ]
        )
        for rec in overdue:
            rec.message_post(
                body=_("Invoice is overdue. Due date: %(date)s") % {"date": rec.due_date},
                subtype_xmlid="mail.mt_note",
            )

            todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
            model_id = self.env["ir.model"]._get_id("lab.request.invoice")
            if not todo:
                continue
            owner = rec.request_id.triaged_by_id or rec.request_id.create_uid or self.env.user
            exists = self.env["mail.activity"].search_count(
                [
                    ("res_model_id", "=", model_id),
                    ("res_id", "=", rec.id),
                    ("summary", "=", "Overdue invoice follow-up"),
                    ("user_id", "=", owner.id),
                ]
            )
            if exists:
                continue
            self.env["mail.activity"].create(
                {
                    "activity_type_id": todo.id,
                    "res_model_id": model_id,
                    "res_id": rec.id,
                    "summary": "Overdue invoice follow-up",
                    "user_id": owner.id,
                    "note": _("Invoice %(name)s is overdue. Please follow up payment.") % {"name": rec.name},
                }
            )

    @api.model
    def create_from_test_request(self, request):
        if not request.line_ids:
            raise UserError(_("Cannot create invoice from request without test lines."))

        partner = request.client_partner_id or request.requester_partner_id
        vals = {
            "request_id": request.id,
            "partner_id": partner.id,
            "currency_id": request.currency_id.id,
            "invoice_date": fields.Date.today(),
            "due_date": fields.Date.add(fields.Date.today(), days=7),
            "line_ids": [],
        }
        for line in request.line_ids:
            description = line.service_id.name if line.line_type == "service" else line.profile_id.name
            vals["line_ids"].append(
                (
                    0,
                    0,
                    {
                        "request_line_id": line.id,
                        "description": description,
                        "quantity": line.quantity,
                        "unit_price": line.unit_price,
                        "discount_percent": line.discount_percent,
                    },
                )
            )
        invoice = self.create(vals)
        invoice.message_post(
            body=_("Invoice generated from test request %(request)s") % {"request": request.name},
            subtype_xmlid="mail.mt_note",
        )
        return invoice


class LabRequestInvoiceLine(models.Model):
    _name = "lab.request.invoice.line"
    _description = "Lab Request Invoice Line"
    _order = "id"

    invoice_id = fields.Many2one("lab.request.invoice", required=True, ondelete="cascade")
    request_line_id = fields.Many2one("lab.test.request.line", ondelete="set null")
    description = fields.Char(required=True)
    quantity = fields.Float(default=1.0, required=True)
    unit_price = fields.Monetary(required=True, currency_field="currency_id")
    discount_percent = fields.Float(default=0.0)

    currency_id = fields.Many2one(related="invoice_id.currency_id", store=True, readonly=True)
    subtotal_gross = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    discount_amount = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)
    subtotal = fields.Monetary(compute="_compute_amount", currency_field="currency_id", store=True)

    @api.depends("quantity", "unit_price", "discount_percent")
    def _compute_amount(self):
        for rec in self:
            qty = max(rec.quantity, 0.0)
            gross = qty * (rec.unit_price or 0.0)
            discount = gross * ((rec.discount_percent or 0.0) / 100.0)
            rec.subtotal_gross = gross
            rec.discount_amount = discount
            rec.subtotal = gross - discount

    @api.constrains("quantity", "unit_price", "discount_percent")
    def _check_amount_fields(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("Invoice line quantity must be greater than 0."))
            if rec.unit_price < 0:
                raise ValidationError(_("Invoice line unit price cannot be negative."))
            if rec.discount_percent < 0 or rec.discount_percent > 100:
                raise ValidationError(_("Invoice line discount percent must be between 0 and 100."))


class LabRequestPayment(models.Model):
    _name = "lab.request.payment"
    _description = "Lab Request Payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False)
    invoice_id = fields.Many2one("lab.request.invoice", required=True, ondelete="cascade", tracking=True)
    request_id = fields.Many2one(related="invoice_id.request_id", store=True, readonly=True)
    payer_partner_id = fields.Many2one("res.partner", required=True)
    amount = fields.Monetary(required=True, currency_field="currency_id")
    currency_id = fields.Many2one(related="invoice_id.currency_id", store=True, readonly=True)

    payment_date = fields.Date(default=fields.Date.today, required=True)
    channel = fields.Selection(
        [
            ("cash", "Cash"),
            ("bank", "Bank Transfer"),
            ("card", "Card"),
            ("wallet", "Wallet"),
            ("other", "Other"),
        ],
        default="bank",
        required=True,
    )
    reference = fields.Char(string="Payment Reference")
    note = fields.Text()

    state = fields.Selection(
        [
            ("pending", "Pending Review"),
            ("confirmed", "Confirmed"),
            ("rejected", "Rejected"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        tracking=True,
    )
    reviewed_at = fields.Datetime(readonly=True)
    reviewed_by_id = fields.Many2one("res.users", readonly=True)
    rejection_reason = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.request.payment") or "New"
        return super().create(vals_list)

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Payment amount must be greater than 0."))

    @api.constrains("invoice_id", "amount")
    def _check_overpay(self):
        for rec in self:
            if rec.state in ("rejected", "cancelled"):
                continue
            invoice = rec.invoice_id
            confirmed_other = sum(
                invoice.payment_ids.filtered(lambda p: p.id != rec.id and p.state == "confirmed").mapped("amount")
            )
            if confirmed_other + rec.amount > invoice.amount_total + 0.00001:
                raise ValidationError(_("Payment exceeds invoice total amount."))

    def action_confirm(self):
        for rec in self:
            if rec.state != "pending":
                continue
            rec.write(
                {
                    "state": "confirmed",
                    "reviewed_at": fields.Datetime.now(),
                    "reviewed_by_id": self.env.user.id,
                    "rejection_reason": False,
                }
            )
            invoice = rec.invoice_id
            if invoice.amount_residual <= 0:
                invoice.state = "paid"
            else:
                invoice.state = "partially_paid"
            invoice.message_post(
                body=_(
                    "Payment %(payment)s confirmed for %(amount).2f. Residual %(residual).2f"
                )
                % {
                    "payment": rec.name,
                    "amount": rec.amount,
                    "residual": invoice.amount_residual,
                },
                subtype_xmlid="mail.mt_note",
            )

    def action_reject(self):
        for rec in self:
            if rec.state != "pending":
                continue
            rec.write(
                {
                    "state": "rejected",
                    "reviewed_at": fields.Datetime.now(),
                    "reviewed_by_id": self.env.user.id,
                }
            )
            rec.invoice_id.message_post(
                body=_("Payment %(payment)s rejected.") % {"payment": rec.name},
                subtype_xmlid="mail.mt_note",
            )

    def action_cancel(self):
        for rec in self:
            if rec.state == "confirmed":
                raise UserError(_("Confirmed payment cannot be cancelled. Reject it with reason instead."))
            rec.state = "cancelled"


class LabTestRequestBillingMixin(models.Model):
    _inherit = "lab.test.request"

    invoice_ids = fields.One2many("lab.request.invoice", "request_id", string="Invoices", readonly=True)
    invoice_count = fields.Integer(compute="_compute_invoice_metrics", compute_sudo=True)
    invoice_amount_total = fields.Monetary(
        compute="_compute_invoice_metrics", currency_field="currency_id", compute_sudo=True
    )
    invoice_amount_paid = fields.Monetary(
        compute="_compute_invoice_metrics", currency_field="currency_id", compute_sudo=True
    )
    invoice_amount_residual = fields.Monetary(
        compute="_compute_invoice_metrics", currency_field="currency_id", compute_sudo=True
    )

    billing_state = fields.Selection(
        [
            ("no_invoice", "No Invoice"),
            ("unpaid", "Unpaid"),
            ("partial", "Partially Paid"),
            ("paid", "Paid"),
        ],
        compute="_compute_invoice_metrics",
        compute_sudo=True,
        store=False,
    )

    payment_policy = fields.Selection(
        [
            ("allow_unpaid", "Allow Sample Creation Before Payment"),
            ("require_paid", "Require Full Payment Before Sample Creation"),
        ],
        compute="_compute_payment_policy",
        store=False,
    )

    @api.depends("invoice_ids", "invoice_ids.amount_total", "invoice_ids.amount_paid", "invoice_ids.amount_residual", "invoice_ids.state")
    def _compute_invoice_metrics(self):
        for rec in self:
            invoices = rec.invoice_ids.filtered(lambda x: x.state != "void")
            rec.invoice_count = len(invoices)
            rec.invoice_amount_total = sum(invoices.mapped("amount_total"))
            rec.invoice_amount_paid = sum(invoices.mapped("amount_paid"))
            rec.invoice_amount_residual = sum(invoices.mapped("amount_residual"))
            if not invoices:
                rec.billing_state = "no_invoice"
            elif rec.invoice_amount_residual <= 0 and rec.invoice_amount_total > 0:
                rec.billing_state = "paid"
            elif rec.invoice_amount_paid > 0:
                rec.billing_state = "partial"
            else:
                rec.billing_state = "unpaid"

    def _compute_payment_policy(self):
        param = self.env["ir.config_parameter"].sudo().get_param(
            "laboratory_management.require_payment_before_sample", "0"
        )
        require_paid = param in ("1", "true", "True")
        for rec in self:
            rec.payment_policy = "require_paid" if require_paid else "allow_unpaid"

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "name": _("Invoices"),
            "type": "ir.actions.act_window",
            "res_model": "lab.request.invoice",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_generate_invoice(self):
        invoice_model = self.env["lab.request.invoice"]
        for rec in self:
            if rec.state not in ("quoted", "approved", "in_progress", "completed"):
                raise UserError(_("Invoice can only be generated after quote stage."))
            existing = rec.invoice_ids.filtered(lambda x: x.state != "void")
            if existing:
                raise UserError(_("Non-void invoice already exists for this request."))
            invoice = invoice_model.create_from_test_request(rec)
            rec.message_post(
                body=_("Invoice <b>%(invoice)s</b> generated.") % {"invoice": invoice.name},
                subtype_xmlid="mail.mt_note",
            )

    def action_create_samples(self):
        self._check_payment_requirement_before_sample()
        return super().action_create_samples()

    def _check_payment_requirement_before_sample(self):
        require_paid = self.env["ir.config_parameter"].sudo().get_param(
            "laboratory_management.require_payment_before_sample", "0"
        ) in ("1", "true", "True")
        if not require_paid:
            return
        for rec in self:
            if rec.billing_state != "paid":
                raise UserError(
                    _(
                        "Full payment is required before sample creation. "
                        "Request %(request)s billing state: %(state)s"
                    )
                    % {
                        "request": rec.name,
                        "state": dict(self._fields["billing_state"].selection).get(rec.billing_state),
                    }
                )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lab_require_payment_before_sample = fields.Boolean(
        string="Require Full Payment Before Sample Creation",
        config_parameter="laboratory_management.require_payment_before_sample",
    )
    lab_auto_invoice_on_approve = fields.Boolean(
        string="Auto Generate Invoice On Quote Approval",
        config_parameter="laboratory_management.auto_invoice_on_approve",
    )


class LabTestRequestAutoInvoiceMixin(models.Model):
    _inherit = "lab.test.request"

    def action_approve_quote(self):
        res = super().action_approve_quote()
        auto_invoice = self.env["ir.config_parameter"].sudo().get_param(
            "laboratory_management.auto_invoice_on_approve", "0"
        ) in ("1", "true", "True")
        if not auto_invoice:
            return res

        invoice_model = self.env["lab.request.invoice"]
        for rec in self:
            if rec.invoice_ids.filtered(lambda x: x.state != "void"):
                continue
            invoice = invoice_model.create_from_test_request(rec)
            rec.message_post(
                body=_("Auto-generated invoice <b>%(invoice)s</b> on quote approval.") % {"invoice": invoice.name},
                subtype_xmlid="mail.mt_note",
            )
        return res

class LabServiceAccountMixin(models.Model):
    _inherit = "lab.service"

    billable_product_id = fields.Many2one(
        "product.product",
        string="Billable Product",
        help="Optional mapped product used when generating native Odoo customer invoices.",
    )

    def _get_or_create_billable_product(self):
        self.ensure_one()
        income_account = self.env["account.account"].search([("internal_group", "=", "income")], limit=1)
        if self.billable_product_id:
            if income_account and not self.billable_product_id.product_tmpl_id.property_account_income_id:
                self.billable_product_id.product_tmpl_id.property_account_income_id = income_account.id
            return self.billable_product_id
        product = self.env["product.product"].create(
            {
                "name": self.name,
                "default_code": f"LAB-{self.code}",
                "type": "service",
                "list_price": self.list_price,
                "sale_ok": True,
                "purchase_ok": False,
                "property_account_income_id": income_account.id if income_account else False,
            }
        )
        self.billable_product_id = product.id
        return product


class AccountMoveLabRequestMixin(models.Model):
    _inherit = "account.move"

    lab_request_id = fields.Many2one("lab.test.request", string="Lab Test Request", index=True)


class LabTestRequestAccountInvoiceMixin(models.Model):
    _inherit = "lab.test.request"

    account_move_ids = fields.One2many("account.move", "lab_request_id", string="Odoo Invoices", readonly=True)
    account_move_count = fields.Integer(compute="_compute_account_move_metrics")
    account_move_payment_state = fields.Selection(
        [
            ("none", "No Invoice"),
            ("not_paid", "Not Paid"),
            ("in_payment", "In Payment"),
            ("paid", "Paid"),
            ("partial", "Partially Paid"),
            ("reversed", "Reversed"),
            ("unknown", "Unknown"),
        ],
        compute="_compute_account_move_metrics",
        store=False,
    )

    def _compute_account_move_metrics(self):
        for rec in self:
            invoices = rec.account_move_ids.filtered(lambda m: m.move_type == "out_invoice")
            rec.account_move_count = len(invoices)
            if not invoices:
                rec.account_move_payment_state = "none"
                continue
            states = set(invoices.mapped("payment_state"))
            if states == {"paid"}:
                rec.account_move_payment_state = "paid"
            elif "in_payment" in states:
                rec.account_move_payment_state = "in_payment"
            elif "partial" in states:
                rec.account_move_payment_state = "partial"
            elif "not_paid" in states:
                rec.account_move_payment_state = "not_paid"
            elif "reversed" in states:
                rec.account_move_payment_state = "reversed"
            else:
                rec.account_move_payment_state = "unknown"

    def action_view_odoo_invoices(self):
        self.ensure_one()
        return {
            "name": _("Odoo Customer Invoices"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("lab_request_id", "=", self.id), ("move_type", "=", "out_invoice")],
            "context": {
                "default_move_type": "out_invoice",
                "default_partner_id": (self.client_partner_id or self.requester_partner_id).id,
                "default_lab_request_id": self.id,
            },
        }

    def action_generate_odoo_invoice(self):
        self.ensure_one()
        if self.state not in ("quoted", "approved", "in_progress", "completed"):
            raise UserError(_("Odoo invoice can only be generated after quote stage."))
        if not self.line_ids:
            raise UserError(_("Cannot generate Odoo invoice without request lines."))

        partner = self.client_partner_id or self.requester_partner_id
        if not partner:
            raise UserError(_("Requester or client partner is required."))
        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        if not journal:
            raise UserError(
                _(
                    "No Sale Journal found for company %(company)s. "
                    "Please configure Accounting before generating native Odoo invoices."
                )
                % {"company": self.env.company.name}
            )

        move_lines = []
        income_account = self.env["account.account"].search([("internal_group", "=", "income")], limit=1)
        if not income_account:
            raise UserError(_("No income account found. Please configure chart of accounts first."))
        for req_line in self.line_ids:
            if req_line.line_type == "service":
                services = req_line.service_id
            else:
                services = req_line.profile_id.line_ids.mapped("service_id")

            for service in services:
                product = service._get_or_create_billable_product()
                if income_account and not product.product_tmpl_id.property_account_income_id:
                    product.product_tmpl_id.property_account_income_id = income_account.id
                move_lines.append(
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "name": service.name,
                            "quantity": req_line.quantity,
                            "price_unit": req_line.unit_price if req_line.line_type == "service" else service.list_price,
                            "discount": req_line.discount_percent,
                            "account_id": income_account.id,
                        },
                    )
                )

        if not move_lines:
            raise UserError(_("No billable lines found for native invoice."))

        move = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": partner.id,
                "invoice_origin": self.name,
                "invoice_date": fields.Date.today(),
                "invoice_date_due": fields.Date.add(fields.Date.today(), days=7),
                "invoice_line_ids": move_lines,
                "lab_request_id": self.id,
                "narration": self.clinical_note,
                "journal_id": journal.id,
            }
        )
        move.action_post()

        self.message_post(
            body=_("Native Odoo invoice <b>%(invoice)s</b> posted.") % {"invoice": move.name},
            subtype_xmlid="mail.mt_note",
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
            "target": "current",
        }

    def _check_payment_requirement_before_sample(self):
        super()._check_payment_requirement_before_sample()

        require_paid_odoo = self.env["ir.config_parameter"].sudo().get_param(
            "laboratory_management.require_odoo_invoice_paid_before_sample", "0"
        ) in ("1", "true", "True")
        if not require_paid_odoo:
            return

        for rec in self:
            invoices = rec.account_move_ids.filtered(lambda m: m.move_type == "out_invoice" and m.state == "posted")
            if not invoices:
                raise UserError(_("Posted Odoo customer invoice is required before sample creation."))
            if any(move.payment_state not in ("paid",) for move in invoices):
                raise UserError(_("All posted Odoo invoices must be fully paid before sample creation."))


class ResConfigSettingsNativeInvoiceMixin(models.TransientModel):
    _inherit = "res.config.settings"

    lab_require_odoo_invoice_paid_before_sample = fields.Boolean(
        string="Require Odoo Invoice Fully Paid Before Sample Creation",
        config_parameter="laboratory_management.require_odoo_invoice_paid_before_sample",
    )
