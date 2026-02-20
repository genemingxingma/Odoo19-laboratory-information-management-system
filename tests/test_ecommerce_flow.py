from odoo.tests.common import TransactionCase


class TestLabEcommerceFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_individual = cls.env["res.partner"].create({"name": "John Individual"})
        cls.partner_professional = cls.env["res.partner"].create(
            {"name": "General Hospital", "is_company": True}
        )

        cls.service_glucose = cls.env["lab.service"].create(
            {
                "name": "Glucose Fast",
                "code": "E2E-GLU",
                "department": "chemistry",
                "sample_type": "blood",
                "result_type": "numeric",
                "turnaround_hours": 8,
                "list_price": 38.0,
            }
        )
        cls.service_urine = cls.env["lab.service"].create(
            {
                "name": "Urine Routine",
                "code": "E2E-URI",
                "department": "chemistry",
                "sample_type": "urine",
                "result_type": "text",
                "turnaround_hours": 6,
                "list_price": 25.0,
            }
        )

        cls.profile_metabolic = cls.env["lab.profile"].create(
            {
                "name": "Metabolic Profile",
                "code": "E2E-PROF",
                "line_ids": [
                    (0, 0, {"service_id": cls.service_glucose.id}),
                    (0, 0, {"service_id": cls.service_urine.id}),
                ],
            }
        )

        cls.product_glucose = cls.env["product.template"].create(
            {
                "name": "Glucose Test Product",
                "list_price": 40.0,
                "sale_ok": True,
                "is_lab_test_product": True,
                "lab_service_id": cls.service_glucose.id,
                "lab_default_priority": "urgent",
                "lab_sale_target": "both",
            }
        ).product_variant_id

        cls.product_urine = cls.env["product.template"].create(
            {
                "name": "Urine Test Product",
                "list_price": 27.0,
                "sale_ok": True,
                "is_lab_test_product": True,
                "lab_service_id": cls.service_urine.id,
                "lab_default_priority": "routine",
                "lab_sale_target": "both",
            }
        ).product_variant_id

        cls.product_profile = cls.env["product.template"].create(
            {
                "name": "Metabolic Panel Product",
                "list_price": 69.0,
                "sale_ok": True,
                "is_lab_test_product": True,
                "lab_profile_id": cls.profile_metabolic.id,
                "lab_default_priority": "stat",
                "lab_sale_target": "both",
            }
        ).product_variant_id

        cls.product_regular = cls.env["product.template"].create(
            {
                "name": "Non Lab Product",
                "list_price": 9.9,
                "sale_ok": True,
            }
        ).product_variant_id

    def _set_flow(self, flow, split=False):
        icp = self.env["ir.config_parameter"].sudo()
        icp.set_param("laboratory_management.ecommerce_request_flow", flow)
        icp.set_param("laboratory_management.ecommerce_split_requests", "1" if split else "0")

    def _create_order(self, partner, lines):
        order_lines = []
        for product, qty in lines:
            order_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "name": product.display_name,
                        "product_uom_qty": qty,
                        "price_unit": product.lst_price,
                    },
                )
            )
        return self.env["sale.order"].create({"partner_id": partner.id, "order_line": order_lines})

    def test_01_default_flow_create_approved_request(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()

        self.assertEqual(order.lab_request_count, 1)
        request = order.lab_request_ids[:1]
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.request_type, "individual")
        self.assertEqual(request.sample_count, 0)

    def test_02_in_progress_flow_creates_sample(self):
        self._set_flow("in_progress", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()

        self.assertEqual(order.lab_request_count, 1)
        request = order.lab_request_ids[:1]
        self.assertEqual(request.state, "in_progress")
        self.assertEqual(request.sample_count, 1)
        self.assertTrue(request.sample_ids)

    def test_03_submitted_flow_stops_before_quote(self):
        self._set_flow("submitted", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()

        request = order.lab_request_ids[:1]
        self.assertEqual(request.state, "submitted")
        self.assertFalse(request.quote_revision_ids)

    def test_04_quoted_flow_keeps_request_quoted(self):
        self._set_flow("quoted", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()

        request = order.lab_request_ids[:1]
        self.assertEqual(request.state, "quoted")
        self.assertTrue(request.quote_revision_ids)

    def test_05_split_requests_by_order_line(self):
        self._set_flow("approved", split=True)
        order = self._create_order(
            self.partner_individual,
            [(self.product_glucose, 1), (self.product_urine, 2)],
        )
        order.action_confirm()

        self.assertEqual(order.lab_request_count, 2)
        for req in order.lab_request_ids:
            self.assertEqual(len(req.line_ids), 1)
            self.assertEqual(req.state, "approved")

    def test_06_grouped_request_contains_multiple_lines(self):
        self._set_flow("approved", split=False)
        order = self._create_order(
            self.partner_individual,
            [(self.product_glucose, 1), (self.product_urine, 2)],
        )
        order.action_confirm()

        self.assertEqual(order.lab_request_count, 1)
        req = order.lab_request_ids[:1]
        self.assertEqual(len(req.line_ids), 2)

    def test_07_confirm_is_idempotent_for_lab_request_creation(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()
        first_count = order.lab_request_count

        order._create_lab_request_from_order()
        self.assertEqual(order.lab_request_count, first_count)

    def test_08_manual_sync_creates_request_for_existing_sale_order(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order.action_confirm()

        order.lab_request_ids.unlink()
        order.invalidate_recordset(["lab_request_ids", "lab_request_count"])
        self.assertEqual(len(order.lab_request_ids), 0)

        order.action_sync_lab_requests()
        order.invalidate_recordset(["lab_request_ids", "lab_request_count"])
        self.assertEqual(len(order.lab_request_ids), 1)

    def test_09_professional_partner_creates_institution_request(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_professional, [(self.product_glucose, 1)])
        order.action_confirm()

        req = order.lab_request_ids[:1]
        self.assertEqual(req.request_type, "institution")
        self.assertEqual(req.client_partner_id, self.partner_professional.commercial_partner_id)

    def test_10_priority_and_sample_type_come_from_mapped_service(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_urine, 1)])
        order.action_confirm()

        req = order.lab_request_ids[:1]
        self.assertEqual(req.priority, "routine")
        self.assertEqual(req.sample_type, "urine")

    def test_11_profile_product_maps_to_profile_line(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_profile, 2)])
        order.action_confirm()

        req = order.lab_request_ids[:1]
        self.assertEqual(len(req.line_ids), 1)
        line = req.line_ids[:1]
        self.assertEqual(line.line_type, "profile")
        self.assertEqual(line.profile_id, self.profile_metabolic)
        self.assertEqual(line.quantity, 2)

    def test_12_non_lab_products_do_not_generate_requests(self):
        self._set_flow("approved", split=False)
        order = self._create_order(self.partner_individual, [(self.product_regular, 1)])
        order.action_confirm()
        self.assertEqual(order.lab_request_count, 0)

    def test_13_mixed_products_generate_only_lab_request_lines(self):
        self._set_flow("approved", split=False)
        order = self._create_order(
            self.partner_individual,
            [(self.product_regular, 1), (self.product_glucose, 1)],
        )
        order.action_confirm()

        self.assertEqual(order.lab_request_count, 1)
        req = order.lab_request_ids[:1]
        self.assertEqual(len(req.line_ids), 1)
        self.assertEqual(req.line_ids.service_id, self.service_glucose)

    def test_14_lab_purchase_type_compute(self):
        order_ind = self._create_order(self.partner_individual, [(self.product_glucose, 1)])
        order_pro = self._create_order(self.partner_professional, [(self.product_glucose, 1)])
        self.assertEqual(order_ind.lab_purchase_type, "individual")
        self.assertEqual(order_pro.lab_purchase_type, "professional")
