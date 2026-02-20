from odoo import _, fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.http import request


class LaboratoryPortal(CustomerPortal):
    PROFESSIONAL_PURCHASE_LINE_KEYS = ("1", "2", "3")

    def _cache_get_or_set(self, key, factory):
        cache = getattr(request, "_lab_portal_cache", None)
        if cache is None:
            cache = {}
            setattr(request, "_lab_portal_cache", cache)
        if key not in cache:
            cache[key] = factory()
        return cache[key]

    def _current_commercial_partner(self):
        return self._cache_get_or_set(
            "commercial_partner",
            lambda: request.env.user.partner_id.commercial_partner_id,
        )

    def _sample_ids_for_current_user(self):
        return self._cache_get_or_set(
            "sample_ids",
            lambda: request.env["lab.sample"].sudo().search(self._sample_domain_for_current_user()).ids,
        )

    def _portal_list_records(self, *, model_name, domain, sortings, sortby, url, page, step=20):
        sort_key = sortby if sortby in sortings else next(iter(sortings.keys()))
        sort_order = sortings[sort_key]["order"]
        model = request.env[model_name].sudo()
        total = model.search_count(domain)
        pager = portal_pager(url=url, total=total, page=page, step=step, url_args={"sortby": sort_key})
        records = model.search(domain, order=sort_order, limit=step, offset=pager["offset"])
        return records, pager, sort_key

    def _sample_domain_for_current_user(self):
        partner = self._current_commercial_partner()
        return [
            "|",
            ("patient_id", "child_of", partner.id),
            ("client_id", "child_of", partner.id),
        ]

    def _batch_domain_for_current_user(self):
        sample_ids = self._sample_ids_for_current_user()
        if not sample_ids:
            return [("id", "=", 0)]
        return [("line_ids.sample_id", "in", sample_ids)]

    def _investigation_domain_for_current_user(self):
        sample_ids = self._sample_ids_for_current_user()
        if not sample_ids:
            return [("id", "=", 0)]
        return ["|", ("sample_id", "in", sample_ids), ("batch_id.line_ids.sample_id", "in", sample_ids)]

    def _request_domain_for_current_user(self):
        partner = self._current_commercial_partner()
        return [
            "|",
            ("requester_partner_id", "child_of", partner.id),
            ("client_partner_id", "child_of", partner.id),
        ]

    def _request_invoice_domain_for_current_user(self):
        partner = self._current_commercial_partner()
        return [
            "|",
            ("request_id.requester_partner_id", "child_of", partner.id),
            ("request_id.client_partner_id", "child_of", partner.id),
        ]

    def _professional_product_domain(self):
        return [
            ("is_lab_test_product", "=", True),
            ("lab_sale_target", "in", ("professional", "both")),
            ("sale_ok", "=", True),
            ("active", "=", True),
        ]

    def _is_professional_partner(self, partner):
        commercial = partner.commercial_partner_id
        return bool(commercial.is_company or partner.is_company or partner.parent_id)

    def _extract_professional_purchase_lines(self, post):
        line_payloads = []

        def _to_int(raw, default=0):
            try:
                return int(raw or default)
            except (TypeError, ValueError):
                return default

        for suffix in self.PROFESSIONAL_PURCHASE_LINE_KEYS:
            raw_product = post.get("product_id_%s" % suffix)
            raw_qty = post.get("quantity_%s" % suffix)
            product_id = _to_int(raw_product, 0)
            qty = _to_int(raw_qty, 0)
            if not product_id and qty <= 0:
                continue
            if not product_id or qty <= 0:
                return []
            line_payloads.append({"product_id": product_id, "quantity": max(qty, 1)})

        # Backward-compatible fallback for old single-line form posts.
        if not line_payloads:
            product_id = _to_int(post.get("product_id"), 0)
            qty = max(_to_int(post.get("quantity"), 1), 1)
            if product_id:
                line_payloads.append({"product_id": product_id, "quantity": qty})
        return line_payloads

    def _professional_history_templates(self, partner, limit=8):
        order_obj = request.env["sale.order"].sudo()
        orders = order_obj.search(
            [
                ("partner_id", "child_of", partner.id),
                ("state", "in", ("sale", "done")),
                ("order_line.product_template_id.is_lab_test_product", "=", True),
            ],
            order="id desc",
            limit=limit,
        )
        templates = []
        for order in orders:
            lines = order.order_line.filtered(lambda l: l.product_template_id.is_lab_test_product and l.product_id)
            if not lines:
                continue
            templates.append(
                {
                    "order": order,
                    "lines": [
                        {
                            "product_id": line.product_id.id,
                            "product_name": line.product_id.display_name,
                            "qty": int(line.product_uom_qty or 0),
                        }
                        for line in lines
                    ],
                }
            )
        return templates

    def _resolve_professional_purchase_lines(self, partner, post):
        lines = self._extract_professional_purchase_lines(post)
        if lines:
            return lines
        reuse_order_id = int(post.get("reuse_order_id") or 0)
        if not reuse_order_id:
            return []
        order = (
            request.env["sale.order"]
            .sudo()
            .search(
                [
                    ("id", "=", reuse_order_id),
                    ("partner_id", "child_of", partner.id),
                    ("state", "in", ("sale", "done")),
                ],
                limit=1,
            )
        )
        if not order:
            return []
        payload = []
        for line in order.order_line.filtered(lambda l: l.product_template_id.is_lab_test_product and l.product_id):
            payload.append({"product_id": line.product_id.id, "quantity": max(int(line.product_uom_qty or 1), 1)})
        return payload

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "lab_sample_count" in counters:
            values["lab_sample_count"] = request.env["lab.sample"].sudo().search_count(self._sample_domain_for_current_user())
        if "lab_custody_batch_count" in counters:
            values["lab_custody_batch_count"] = request.env["lab.sample.custody.batch"].sudo().search_count(
                self._batch_domain_for_current_user()
            )
        if "lab_custody_investigation_count" in counters:
            values["lab_custody_investigation_count"] = request.env["lab.custody.investigation"].sudo().search_count(
                self._investigation_domain_for_current_user()
            )
        if "lab_test_request_count" in counters:
            values["lab_test_request_count"] = request.env["lab.test.request"].sudo().search_count(
                self._request_domain_for_current_user()
            )
        if "lab_request_invoice_count" in counters:
            values["lab_request_invoice_count"] = request.env["lab.request.invoice"].sudo().search_count(
                self._request_invoice_domain_for_current_user()
            )
        return values

    def _get_authorized_sample(self, sample_id):
        sample_domain = [("id", "=", sample_id)] + self._sample_domain_for_current_user()
        return request.env["lab.sample"].sudo().search(sample_domain, limit=1) or None

    def _get_authorized_batch(self, batch_id):
        domain = [("id", "=", batch_id)] + self._batch_domain_for_current_user()
        return request.env["lab.sample.custody.batch"].sudo().search(domain, limit=1) or None

    def _get_authorized_investigation(self, investigation_id):
        domain = [("id", "=", investigation_id)] + self._investigation_domain_for_current_user()
        return request.env["lab.custody.investigation"].sudo().search(domain, limit=1) or None

    def _get_authorized_request(self, request_id):
        domain = [("id", "=", request_id)] + self._request_domain_for_current_user()
        return request.env["lab.test.request"].sudo().search(domain, limit=1) or None

    def _get_authorized_request_invoice(self, invoice_id):
        domain = [("id", "=", invoice_id)] + self._request_invoice_domain_for_current_user()
        return request.env["lab.request.invoice"].sudo().search(domain, limit=1) or None

    @http.route(["/my/lab/samples", "/my/lab/samples/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_samples(self, page=1, sortby="date", **kwargs):
        domain = self._sample_domain_for_current_user()
        sortings = {
            "date": {"label": _("Newest"), "order": "id desc"},
            "name": {"label": _("Accession"), "order": "name asc"},
            "state": {"label": _("Status"), "order": "state asc, id desc"},
            "report": {"label": _("Report Date"), "order": "report_date desc, id desc"},
        }
        samples, pager, sortby = self._portal_list_records(
            model_name="lab.sample",
            domain=domain,
            sortings=sortings,
            sortby=sortby,
            url="/my/lab/samples",
            page=page,
        )

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "records": samples,
                "page_name": "lab_samples",
                "pager": pager,
                "default_url": "/my/lab/samples",
                "sortings": sortings,
                "sortby": sortby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_samples", values)

    @http.route("/my/lab/samples/<int:sample_id>", type="http", auth="user", website=True)
    def portal_sample_detail(self, sample_id, **kwargs):
        sample = self._get_authorized_sample(sample_id)
        if not sample:
            return request.redirect("/my")

        values = self._prepare_portal_layout_values()
        values.update({"record": sample, "page_name": "lab_samples"})
        return request.render("laboratory_management.portal_my_lab_sample_detail", values)

    @http.route("/my/lab/samples/<int:sample_id>/report", type="http", auth="user", website=True)
    def portal_sample_report_default(self, sample_id, **kwargs):
        return request.redirect("/my/lab/samples/%s/report/h5" % sample_id)

    @http.route("/my/lab/samples/<int:sample_id>/report/h5", type="http", auth="user", website=True)
    def portal_sample_report_h5(self, sample_id, **kwargs):
        sample = self._get_authorized_sample(sample_id)
        if not sample:
            return request.redirect("/my/lab/samples")
        if sample.report_publication_state == "withdrawn":
            return request.redirect("/my/lab/samples/%s?withdrawn=1" % sample.id)
        partner = self._current_commercial_partner()
        dispatch = request.env["lab.report.dispatch"].sudo().portal_find_dispatch_for_partner(sample, partner)
        if dispatch:
            dispatch.action_mark_viewed()

        values = self._prepare_portal_layout_values()
        values.update({"record": sample, "page_name": "lab_samples", "dispatch": dispatch})
        return request.render("laboratory_management.portal_my_lab_sample_report_h5", values)

    @http.route("/my/lab/samples/<int:sample_id>/report/pdf", type="http", auth="user", website=True)
    def portal_sample_report_download(self, sample_id, **kwargs):
        sample = self._get_authorized_sample(sample_id)
        if not sample or sample.state not in ("verified", "reported") or sample.report_publication_state == "withdrawn":
            return request.redirect("/my/lab/samples/%s/report/h5" % sample_id)
        partner = self._current_commercial_partner()
        dispatch = request.env["lab.report.dispatch"].sudo().portal_find_dispatch_for_partner(sample, partner)
        if dispatch:
            dispatch.action_mark_downloaded()

        action_xmlid = sample.get_report_action_xmlid()
        action = request.env.ref(action_xmlid).sudo()
        pdf_content, _content_type = action._render_qweb_pdf(sample.ids)
        filename = f"{sample.name}.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf_content))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
        ]
        return request.make_response(pdf_content, headers=headers)

    @http.route(
        "/my/lab/samples/<int:sample_id>/report/ai",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_sample_report_ai(self, sample_id, **kwargs):
        sample = self._get_authorized_sample(sample_id)
        if not sample:
            return request.redirect("/my/lab/samples")
        try:
            sample.with_context(
                ai_trigger_source="portal",
                force_ai_regenerate=True,
            ).action_generate_ai_interpretation()
        except Exception:
            pass
        return request.redirect("/my/lab/samples/%s/report/h5" % sample_id)

    @http.route(
        "/my/lab/samples/<int:sample_id>/report/ack",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def portal_sample_report_ack(self, sample_id, ack_name=None, ack_note=None, **kwargs):
        sample = self._get_authorized_sample(sample_id)
        if not sample:
            return request.redirect("/my/lab/samples")
        if sample.report_publication_state == "withdrawn":
            return request.redirect("/my/lab/samples/%s?withdrawn=1" % sample.id)
        partner = self._current_commercial_partner()
        dispatch = request.env["lab.report.dispatch"].sudo().portal_find_dispatch_for_partner(sample, partner)
        if dispatch:
            signer = (ack_name or "").strip() or partner.name
            note = (ack_note or "").strip() or False
            consent = kwargs.get("ack_consent") in ("on", "1", "true", "True")
            if not consent:
                return request.redirect("/my/lab/samples/%s/report/h5?ack_error=consent" % sample.id)
            ip_addr = request.httprequest.remote_addr or ""
            user_agent = request.httprequest.headers.get("User-Agent", "")
            dispatch.create_portal_signature(signer, note, consent, ip_addr, user_agent, partner)
            dispatch.action_acknowledge(signer_name=signer, note=note)
        return request.redirect("/my/lab/samples/%s/report/h5" % sample_id)

    @http.route(["/my/lab/requests", "/my/lab/requests/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_test_requests(self, page=1, sortby="date", **kwargs):
        domain = self._request_domain_for_current_user()
        sortings = {
            "date": {"label": _("Newest"), "order": "id desc"},
            "name": {"label": _("Request No."), "order": "name asc"},
            "state": {"label": _("State"), "order": "state asc, id desc"},
            "amount": {"label": _("Amount"), "order": "amount_total desc, id desc"},
        }
        records, pager, sortby = self._portal_list_records(
            model_name="lab.test.request",
            domain=domain,
            sortings=sortings,
            sortby=sortby,
            url="/my/lab/requests",
            page=page,
        )

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "records": records,
                "page_name": "lab_test_requests",
                "pager": pager,
                "default_url": "/my/lab/requests",
                "sortings": sortings,
                "sortby": sortby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_test_requests", values)

    @http.route("/my/lab/requests/new", type="http", auth="user", website=True, methods=["GET"])
    def portal_test_request_new_form(self, **kwargs):
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "page_name": "lab_test_requests",
                "services": request.env["lab.service"].sudo().search([("active", "=", True)], order="name asc"),
                "profiles": request.env["lab.profile"].sudo().search([("active", "=", True)], order="name asc"),
                "templates": request.env["lab.report.template"].sudo().search([], order="name asc"),
            }
        )
        return request.render("laboratory_management.portal_my_lab_test_request_new", values)

    @http.route("/my/lab/requests/new", type="http", auth="user", website=True, methods=["POST"])
    def portal_test_request_create(self, **post):
        partner = self._current_commercial_partner()
        line_type = (post.get("line_type") or "service").strip()
        request_type = (post.get("request_type") or "individual").strip()
        service_id = int(post.get("service_id") or 0)
        profile_id = int(post.get("profile_id") or 0)
        qty = max(int(post.get("quantity") or 1), 1)
        if line_type == "service" and not service_id:
            return request.redirect("/my/lab/requests/new?error=service")
        if line_type == "profile" and not profile_id:
            return request.redirect("/my/lab/requests/new?error=profile")

        values = {
            "requester_partner_id": partner.id,
            "request_type": request_type,
            "client_partner_id": int(post.get("client_partner_id") or 0) or (partner.id if request_type == "institution" else False),
            "patient_name": (post.get("patient_name") or "").strip(),
            "patient_identifier": (post.get("patient_identifier") or "").strip(),
            "patient_phone": (post.get("patient_phone") or "").strip(),
            "physician_name": (post.get("physician_name") or "").strip(),
            "clinical_note": (post.get("clinical_note") or "").strip(),
            "priority": (post.get("priority") or "routine").strip(),
            "sample_type": (post.get("sample_type") or "blood").strip(),
            "fasting_required": post.get("fasting_required") in ("on", "true", "1"),
            "preferred_template_id": int(post.get("preferred_template_id") or 0) or False,
            "line_ids": [
                (
                    0,
                    0,
                    {
                        "line_type": line_type,
                        "service_id": service_id or False,
                        "profile_id": profile_id or False,
                        "quantity": qty,
                        "note": (post.get("line_note") or "").strip(),
                    },
                )
            ],
        }
        test_request = request.env["lab.test.request"].sudo().create(values)
        if post.get("submit_now") in ("on", "true", "1"):
            test_request.action_submit()
        return request.redirect("/my/lab/requests/%s" % test_request.id)

    @http.route("/my/lab/requests/<int:request_id>", type="http", auth="user", website=True)
    def portal_test_request_detail(self, request_id, **kwargs):
        test_request = self._get_authorized_request(request_id)
        if not test_request:
            return request.redirect("/my/lab/requests")

        values = self._prepare_portal_layout_values()
        values.update({"record": test_request, "page_name": "lab_test_requests"})
        return request.render("laboratory_management.portal_my_lab_test_request_detail", values)

    @http.route("/my/lab/requests/<int:request_id>/submit", type="http", auth="user", website=True, methods=["POST"])
    def portal_test_request_submit(self, request_id, **kwargs):
        test_request = self._get_authorized_request(request_id)
        if not test_request:
            return request.redirect("/my/lab/requests")
        if test_request.state in ("draft", "cancelled"):
            test_request.sudo().action_submit()
        return request.redirect("/my/lab/requests/%s" % request_id)

    @http.route(["/my/lab/invoices", "/my/lab/invoices/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_request_invoices(self, page=1, sortby="date", **kwargs):
        domain = self._request_invoice_domain_for_current_user()
        sortings = {
            "date": {"label": _("Newest"), "order": "id desc"},
            "name": {"label": _("Invoice No."), "order": "name asc"},
            "due": {"label": _("Due Date"), "order": "due_date asc, id desc"},
            "state": {"label": _("State"), "order": "state asc, id desc"},
            "residual": {"label": _("Outstanding"), "order": "amount_residual desc, id desc"},
        }
        records, pager, sortby = self._portal_list_records(
            model_name="lab.request.invoice",
            domain=domain,
            sortings=sortings,
            sortby=sortby,
            url="/my/lab/invoices",
            page=page,
        )

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "records": records,
                "page_name": "lab_request_invoices",
                "pager": pager,
                "default_url": "/my/lab/invoices",
                "sortings": sortings,
                "sortby": sortby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_request_invoices", values)

    @http.route("/my/lab/invoices/<int:invoice_id>", type="http", auth="user", website=True)
    def portal_request_invoice_detail(self, invoice_id, **kwargs):
        invoice = self._get_authorized_request_invoice(invoice_id)
        if not invoice:
            return request.redirect("/my/lab/invoices")
        invoice.write({"portal_last_viewed_at": fields.Datetime.now()})
        values = self._prepare_portal_layout_values()
        values.update({"record": invoice, "page_name": "lab_request_invoices"})
        return request.render("laboratory_management.portal_my_lab_request_invoice_detail", values)

    @http.route("/my/lab/invoices/<int:invoice_id>/pay", type="http", auth="user", website=True, methods=["POST"])
    def portal_request_invoice_pay(self, invoice_id, **post):
        invoice = self._get_authorized_request_invoice(invoice_id)
        if not invoice:
            return request.redirect("/my/lab/invoices")
        if invoice.state not in ("issued", "partially_paid"):
            return request.redirect("/my/lab/invoices/%s?pay_error=state" % invoice_id)

        try:
            amount = float(post.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0
        if amount <= 0:
            return request.redirect("/my/lab/invoices/%s?pay_error=amount" % invoice_id)
        payer = self._current_commercial_partner()

        request.env["lab.request.payment"].sudo().create(
            {
                "invoice_id": invoice.id,
                "payer_partner_id": payer.id,
                "amount": amount,
                "channel": (post.get("channel") or "bank").strip(),
                "reference": (post.get("reference") or "").strip(),
                "note": (post.get("note") or "").strip(),
                "state": "pending",
            }
        )
        invoice.message_post(
            body=_("Portal payment submission received and pending review."),
            subtype_xmlid="mail.mt_note",
        )
        return request.redirect("/my/lab/invoices/%s" % invoice_id)

    @http.route("/my/lab/professional/purchase", type="http", auth="user", website=True, methods=["GET"])
    def portal_professional_purchase_form(self, **kwargs):
        partner = self._current_commercial_partner()
        if not self._is_professional_partner(partner):
            return request.redirect("/my?error=professional_only")
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "page_name": "lab_professional_purchase",
                "products": request.env["product.product"].sudo().search(self._professional_product_domain(), order="name asc"),
                "history_templates": self._professional_history_templates(partner),
            }
        )
        return request.render("laboratory_management.portal_lab_professional_purchase", values)

    @http.route("/my/lab/professional/purchase", type="http", auth="user", website=True, methods=["POST"])
    def portal_professional_purchase_submit(self, **post):
        partner = self._current_commercial_partner()
        if not self._is_professional_partner(partner):
            return request.redirect("/my?error=professional_only")

        line_payloads = self._resolve_professional_purchase_lines(partner, post)
        if not line_payloads:
            return request.redirect("/my/lab/professional/purchase?error=product")

        products = request.env["product.product"].sudo().browse([row["product_id"] for row in line_payloads]).exists()
        product_map = {p.id: p for p in products}
        order_line = []
        for row in line_payloads:
            product = product_map.get(row["product_id"])
            if (
                not product
                or not product.is_lab_test_product
                or product.lab_sale_target not in ("professional", "both")
            ):
                return request.redirect("/my/lab/professional/purchase?error=product")
            order_line.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_uom_qty": row["quantity"],
                        "price_unit": product.lst_price,
                        "name": product.display_name,
                    },
                )
            )

        submit_mode = (post.get("submit_mode") or "quote").strip()
        if submit_mode == "cart":
            cart_order = request.website.sale_get_order(force_create=True)
            for line in order_line:
                values = line[2]
                cart_order._cart_update(
                    product_id=values["product_id"],
                    add_qty=values["product_uom_qty"],
                )
            return request.redirect("/shop/cart")

        sale_order = request.env["sale.order"].sudo().create(
            {
                "partner_id": partner.id,
                "origin": "Portal Professional Purchase",
                "note": (post.get("note") or "").strip() or False,
                "order_line": order_line,
            }
        )
        if submit_mode == "confirm":
            sale_order.action_confirm()
        return request.redirect("/my/orders/%s" % sale_order.id)

    @http.route(["/my/lab/custody/batches", "/my/lab/custody/batches/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_custody_batches(self, page=1, sortby="date", **kwargs):
        domain = self._batch_domain_for_current_user()
        sortings = {
            "date": {"label": _("Newest"), "order": "id desc"},
            "name": {"label": _("Batch"), "order": "name asc"},
            "state": {"label": _("State"), "order": "state asc, id desc"},
            "dispatch": {"label": _("Dispatch"), "order": "dispatch_time desc, id desc"},
        }
        records, pager, sortby = self._portal_list_records(
            model_name="lab.sample.custody.batch",
            domain=domain,
            sortings=sortings,
            sortby=sortby,
            url="/my/lab/custody/batches",
            page=page,
        )

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "records": records,
                "page_name": "lab_custody_batches",
                "pager": pager,
                "default_url": "/my/lab/custody/batches",
                "sortings": sortings,
                "sortby": sortby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_custody_batches", values)

    @http.route("/my/lab/custody/batches/<int:batch_id>", type="http", auth="user", website=True)
    def portal_custody_batch_detail(self, batch_id, **kwargs):
        batch = self._get_authorized_batch(batch_id)
        if not batch:
            return request.redirect("/my/lab/custody/batches")

        values = self._prepare_portal_layout_values()
        values.update({"record": batch, "page_name": "lab_custody_batches"})
        return request.render("laboratory_management.portal_my_lab_custody_batch_detail", values)

    @http.route("/my/lab/custody/batches/<int:batch_id>/manifest", type="http", auth="user", website=True)
    def portal_custody_batch_manifest_download(self, batch_id, **kwargs):
        batch = self._get_authorized_batch(batch_id)
        if not batch:
            return request.redirect("/my/lab/custody/batches")

        action = request.env.ref("laboratory_management.action_report_lab_custody_manifest").sudo()
        pdf_content, _content_type = action._render_qweb_pdf(batch.ids)
        filename = f"Custody-Manifest-{batch.name}.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf_content))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
        ]
        return request.make_response(pdf_content, headers=headers)

    @http.route(
        ["/my/lab/custody/investigations", "/my/lab/custody/investigations/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
    )
    def portal_my_custody_investigations(self, page=1, sortby="date", **kwargs):
        domain = self._investigation_domain_for_current_user()
        sortings = {
            "date": {"label": _("Newest"), "order": "id desc"},
            "name": {"label": _("Investigation"), "order": "name asc"},
            "state": {"label": _("State"), "order": "state asc, id desc"},
            "severity": {"label": _("Severity"), "order": "severity desc, id desc"},
            "deadline": {"label": _("Deadline"), "order": "target_close_date asc, id desc"},
        }
        records, pager, sortby = self._portal_list_records(
            model_name="lab.custody.investigation",
            domain=domain,
            sortings=sortings,
            sortby=sortby,
            url="/my/lab/custody/investigations",
            page=page,
        )

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "records": records,
                "page_name": "lab_custody_investigations",
                "pager": pager,
                "default_url": "/my/lab/custody/investigations",
                "sortings": sortings,
                "sortby": sortby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_custody_investigations", values)

    @http.route("/my/lab/custody/investigations/<int:investigation_id>", type="http", auth="user", website=True)
    def portal_custody_investigation_detail(self, investigation_id, **kwargs):
        record = self._get_authorized_investigation(investigation_id)
        if not record:
            return request.redirect("/my/lab/custody/investigations")

        values = self._prepare_portal_layout_values()
        values.update({"record": record, "page_name": "lab_custody_investigations"})
        return request.render("laboratory_management.portal_my_lab_custody_investigation_detail", values)

    @http.route(
        "/my/lab/custody/investigations/<int:investigation_id>/summary",
        type="http",
        auth="user",
        website=True,
    )
    def portal_custody_investigation_summary_download(self, investigation_id, **kwargs):
        record = self._get_authorized_investigation(investigation_id)
        if not record:
            return request.redirect("/my/lab/custody/investigations")

        action = request.env.ref("laboratory_management.action_report_lab_custody_investigation").sudo()
        pdf_content, _content_type = action._render_qweb_pdf(record.ids)
        filename = f"Investigation-{record.name}.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf_content))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
        ]
        return request.make_response(pdf_content, headers=headers)
