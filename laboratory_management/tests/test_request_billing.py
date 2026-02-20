from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestLabRequestBilling(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        sale_journal = cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", company.id)],
            limit=1,
        )
        if not sale_journal:
            cls.env["account.journal"].create(
                {
                    "name": "Laboratory Sales",
                    "code": "LBSL",
                    "type": "sale",
                    "company_id": company.id,
                }
            )

        cls.partner = cls.env["res.partner"].create({"name": "Portal Patient"})
        cls.client = cls.env["res.partner"].create({"name": "City Hospital", "is_company": True})

        cls.service_glucose = cls.env["lab.service"].create(
            {
                "name": "Glucose",
                "code": "GLU",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "turnaround_hours": 24,
                "list_price": 30.0,
            }
        )
        cls.service_crp = cls.env["lab.service"].create(
            {
                "name": "CRP",
                "code": "CRP",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "turnaround_hours": 12,
                "list_price": 50.0,
            }
        )

        cls.profile = cls.env["lab.profile"].create(
            {
                "name": "Inflammation Panel",
                "code": "INF-PNL",
                "line_ids": [
                    (0, 0, {"service_id": cls.service_glucose.id}),
                    (0, 0, {"service_id": cls.service_crp.id}),
                ],
            }
        )

    def _create_request(self, line_type="service"):
        line_vals = {
            "line_type": line_type,
            "quantity": 1,
            "unit_price": 30.0,
            "discount_percent": 0.0,
        }
        if line_type == "service":
            line_vals["service_id"] = self.service_glucose.id
        else:
            line_vals["profile_id"] = self.profile.id
            line_vals["unit_price"] = 80.0

        request = self.env["lab.test.request"].create(
            {
                "requester_partner_id": self.partner.id,
                "client_partner_id": self.client.id,
                "request_type": "institution",
                "patient_name": "Test Person",
                "priority": "routine",
                "sample_type": "blood",
                "line_ids": [(0, 0, line_vals)],
            }
        )
        return request

    def test_01_submit_quote_approve_flow(self):
        request = self._create_request()
        self.assertEqual(request.state, "draft")

        request.action_submit()
        self.assertEqual(request.state, "submitted")
        self.assertTrue(request.submitted_at)

        request.action_start_triage()
        self.assertEqual(request.state, "triage")

        request.action_prepare_quote()
        self.assertEqual(request.state, "quoted")
        self.assertTrue(request.quote_reference)
        self.assertEqual(request.quote_revision_count, 1)

        request.action_create_quote_revision()
        self.assertEqual(request.quote_revision_count, 2)

        request.action_approve_quote()
        self.assertEqual(request.state, "approved")

    def test_02_generate_custom_invoice(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()

        request.action_generate_invoice()
        self.assertEqual(request.invoice_count, 1)

        invoice = request.invoice_ids[0]
        self.assertEqual(invoice.state, "draft")
        self.assertGreater(invoice.amount_total, 0.0)
        self.assertEqual(invoice.partner_id, self.client)

        invoice.action_issue()
        self.assertEqual(invoice.state, "issued")
        self.assertEqual(invoice.payment_state, "unpaid")

    def test_03_prevent_duplicate_invoice(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()

        request.action_generate_invoice()
        with self.assertRaises(UserError):
            request.action_generate_invoice()

    def test_04_payment_confirm_changes_invoice_state(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()
        request.action_generate_invoice()

        invoice = request.invoice_ids[0]
        invoice.action_issue()

        payment = self.env["lab.request.payment"].create(
            {
                "invoice_id": invoice.id,
                "payer_partner_id": self.partner.id,
                "amount": invoice.amount_total / 2.0,
                "channel": "bank",
            }
        )
        payment.action_confirm()
        self.assertEqual(invoice.state, "partially_paid")
        self.assertEqual(invoice.payment_state, "partial")

        payment2 = self.env["lab.request.payment"].create(
            {
                "invoice_id": invoice.id,
                "payer_partner_id": self.partner.id,
                "amount": invoice.amount_total - payment.amount,
                "channel": "card",
            }
        )
        payment2.action_confirm()

        invoice.invalidate_recordset()
        self.assertEqual(invoice.state, "paid")
        self.assertEqual(invoice.payment_state, "paid")
        self.assertAlmostEqual(invoice.amount_residual, 0.0)

    def test_05_overpayment_blocked(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()
        request.action_generate_invoice()
        invoice = request.invoice_ids[0]

        with self.assertRaises(ValidationError):
            self.env["lab.request.payment"].create(
                {
                    "invoice_id": invoice.id,
                    "payer_partner_id": self.partner.id,
                    "amount": invoice.amount_total + 1.0,
                    "channel": "bank",
                }
            )

    def test_06_sample_creation_requires_custom_payment_when_enabled(self):
        request = self._create_request(line_type="profile")
        request.action_submit()
        request.action_prepare_quote()
        request.action_approve_quote()
        request.action_generate_invoice()

        invoice = request.invoice_ids[0]
        invoice.action_issue()

        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.require_payment_before_sample", "1"
        )

        with self.assertRaises(UserError):
            request.action_create_samples()

        payment = self.env["lab.request.payment"].create(
            {
                "invoice_id": invoice.id,
                "payer_partner_id": self.partner.id,
                "amount": invoice.amount_total,
                "channel": "bank",
            }
        )
        payment.action_confirm()

        request.action_create_samples()
        self.assertEqual(request.state, "in_progress")
        self.assertEqual(request.sample_count, 1)

        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.require_payment_before_sample", "0"
        )

    def test_07_generate_native_odoo_invoice(self):
        request = self._create_request(line_type="profile")
        request.action_submit()
        request.action_prepare_quote()

        try:
            action = request.action_generate_odoo_invoice()
        except UserError as exc:
            self.assertIn("income account", str(exc).lower())
            return
        self.assertEqual(action["res_model"], "account.move")

        self.assertEqual(request.account_move_count, 1)
        move = request.account_move_ids[0]
        self.assertEqual(move.move_type, "out_invoice")
        self.assertEqual(move.state, "posted")
        self.assertTrue(move.invoice_line_ids)
        self.assertEqual(move.lab_request_id, request)

    def test_08_require_native_invoice_paid_policy(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()
        request.action_approve_quote()

        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.require_odoo_invoice_paid_before_sample", "1"
        )

        with self.assertRaises(UserError):
            request.action_create_samples()

        try:
            request.action_generate_odoo_invoice()
        except UserError as exc:
            self.assertIn("income account", str(exc).lower())
            self.env["ir.config_parameter"].sudo().set_param(
                "laboratory_management.require_odoo_invoice_paid_before_sample", "0"
            )
            return
        with self.assertRaises(UserError):
            request.action_create_samples()

        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.require_odoo_invoice_paid_before_sample", "0"
        )

    def test_09_invoice_due_date_validation(self):
        request = self._create_request()
        with self.assertRaises(ValidationError):
            self.env["lab.request.invoice"].create(
                {
                    "request_id": request.id,
                    "partner_id": self.partner.id,
                    "invoice_date": "2026-01-10",
                    "due_date": "2026-01-09",
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "description": "Bad date line",
                                "quantity": 1,
                                "unit_price": 10,
                            },
                        )
                    ],
                }
            )

    def test_10_invoice_line_validation(self):
        request = self._create_request()
        invoice = self.env["lab.request.invoice"].create(
            {
                "request_id": request.id,
                "partner_id": self.partner.id,
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "description": "Valid line",
                            "quantity": 1,
                            "unit_price": 10,
                        },
                    )
                ],
            }
        )
        self.assertEqual(len(invoice.line_ids), 1)

        with self.assertRaises(ValidationError):
            self.env["lab.request.invoice.line"].create(
                {
                    "invoice_id": invoice.id,
                    "description": "Invalid qty",
                    "quantity": 0,
                    "unit_price": 10,
                }
            )

    def test_11_quote_revision_uniqueness(self):
        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()
        rev1 = request.quote_revision_ids[0]

        with self.assertRaises(ValidationError):
            self.env["lab.test.request.quote.revision"].create(
                {
                    "request_id": request.id,
                    "revision_no": rev1.revision_no,
                    "amount_untaxed": 1,
                    "amount_discount": 0,
                    "amount_total": 1,
                    "reason": "duplicate",
                }
            )

    def test_12_auto_invoice_on_approve(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.auto_invoice_on_approve", "1"
        )

        request = self._create_request()
        request.action_submit()
        request.action_prepare_quote()
        request.action_approve_quote()

        self.assertEqual(request.invoice_count, 1)

        self.env["ir.config_parameter"].sudo().set_param(
            "laboratory_management.auto_invoice_on_approve", "0"
        )
