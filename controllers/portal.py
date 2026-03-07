import json
import os

from odoo import _, fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.http import request
from odoo.exceptions import ValidationError, UserError


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

    def _portal_list_records(self, *, model_name, domain, sortings, sortby, url, page, step=20, url_args=None):
        sort_key = sortby if sortby in sortings else next(iter(sortings.keys()))
        sort_order = sortings[sort_key]["order"]
        model = request.env[model_name].sudo()
        total = model.search_count(domain)
        pager = portal_pager(url=url, total=total, page=page, step=step, url_args={"sortby": sort_key, **(url_args or {})})
        records = model.search(domain, order=sort_order, limit=step, offset=pager["offset"])
        return records, pager, sort_key

    def _sample_domain_for_current_user(self):
        partner = self._current_commercial_partner()
        companies = request.env.companies.ids
        return [
            ("company_id", "in", companies),
            "|",
            ("request_id.requester_partner_id", "child_of", partner.id),
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
        companies = request.env.companies.ids
        return [
            ("company_id", "in", companies),
            "|",
            ("requester_partner_id", "child_of", partner.id),
            ("client_partner_id", "child_of", partner.id),
        ]

    def _request_invoice_domain_for_current_user(self):
        partner = self._current_commercial_partner()
        companies = request.env.companies.ids
        return [
            ("company_id", "in", companies),
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

    def _normalize_id_list(self, raw):
        if isinstance(raw, (list, tuple)):
            values = raw
        elif isinstance(raw, str):
            values = [v.strip() for v in raw.split(",") if v.strip()]
        else:
            values = []
        return [int(v) for v in values if str(v).isdigit()]

    def _extract_request_attachments_from_post(self):
        files = request.httprequest.files.getlist("request_attachments")
        payload = []
        for f in files:
            filename = os.path.basename((getattr(f, "filename", "") or "").strip())
            content = f.read() if hasattr(f, "read") else b""
            if not filename or not content:
                continue
            payload.append(
                {
                    "name": filename,
                    "content": content,
                    "mimetype": (getattr(f, "mimetype", None) or "application/octet-stream"),
                }
            )
        return payload

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

    def _sample_filter_options(self):
        return {
            "all": {"label": _("All"), "domain": []},
            "active": {"label": _("In Progress"), "domain": [("state", "in", ("draft", "received", "in_progress", "to_verify", "verified"))]},
            "reported": {"label": _("Reported"), "domain": [("state", "=", "reported"), ("report_publication_state", "=", "active")]},
            "withdrawn": {"label": _("Withdrawn"), "domain": [("report_publication_state", "=", "withdrawn")]},
        }

    def _request_filter_options(self):
        return {
            "all": {"label": _("All"), "domain": []},
            "draft": {"label": _("Draft"), "domain": [("state", "=", "draft")]},
            "pending": {"label": _("Pending Review"), "domain": [("state", "in", ("submitted", "triage", "quoted", "approved"))]},
            "running": {"label": _("In Progress"), "domain": [("state", "=", "in_progress")]},
            "done": {"label": _("Completed"), "domain": [("state", "=", "completed")]},
        }

    def _invoice_filter_options(self):
        return {
            "all": {"label": _("All"), "domain": []},
            "open": {"label": _("Outstanding"), "domain": [("state", "in", ("issued", "partially_paid"))]},
            "paid": {"label": _("Paid"), "domain": [("state", "=", "paid")]},
            "void": {"label": _("Void"), "domain": [("state", "=", "void")]},
        }

    def _apply_filter_domain(self, base_domain, filter_map, filterby):
        filter_key = filterby if filterby in filter_map else next(iter(filter_map.keys()))
        return base_domain + filter_map[filter_key]["domain"], filter_key

    def _prepare_lab_dashboard_values(self):
        partner = self._current_commercial_partner()
        sample_obj = request.env["lab.sample"].sudo()
        request_obj = request.env["lab.test.request"].sudo()
        invoice_obj = request.env["lab.request.invoice"].sudo()

        sample_domain = self._sample_domain_for_current_user()
        request_domain = self._request_domain_for_current_user()
        invoice_domain = self._request_invoice_domain_for_current_user()

        sample_state_domains = {
            "received": sample_domain + [("state", "=", "received")],
            "in_progress": sample_domain + [("state", "=", "in_progress")],
            "to_verify": sample_domain + [("state", "=", "to_verify")],
            "reported": sample_domain + [("state", "=", "reported"), ("report_publication_state", "=", "active")],
        }
        request_state_domains = {
            "draft": request_domain + [("state", "=", "draft")],
            "pending": request_domain + [("state", "in", ("submitted", "triage", "quoted", "approved"))],
            "running": request_domain + [("state", "=", "in_progress")],
            "completed": request_domain + [("state", "=", "completed")],
        }
        invoice_state_domains = {
            "open": invoice_domain + [("state", "in", ("issued", "partially_paid"))],
            "paid": invoice_domain + [("state", "=", "paid")],
        }

        values = {
            "lab_portal_partner": partner,
            "lab_portal_is_professional": self._is_professional_partner(partner),
            "lab_dashboard_samples": {key: sample_obj.search_count(domain) for key, domain in sample_state_domains.items()},
            "lab_dashboard_requests": {key: request_obj.search_count(domain) for key, domain in request_state_domains.items()},
            "lab_dashboard_invoices": {key: invoice_obj.search_count(domain) for key, domain in invoice_state_domains.items()},
            "lab_dashboard_recent_reports": sample_obj.search(
                sample_domain + [("state", "=", "reported"), ("report_publication_state", "=", "active")],
                order="report_date desc, id desc",
                limit=5,
            ),
            "lab_dashboard_recent_requests": request_obj.search(request_domain, order="id desc", limit=5),
            "lab_dashboard_recent_invoices": invoice_obj.search(invoice_domain, order="id desc", limit=5),
            "lab_dashboard_pending_requests": request_obj.search(
                request_domain + [("state", "in", ("submitted", "triage", "quoted", "approved"))],
                order="write_date desc, id desc",
                limit=5,
            ),
        }
        return values

    @http.route("/my/lab/dashboard", type="http", auth="user", website=True)
    def portal_lab_dashboard(self, **kwargs):
        values = self._prepare_portal_layout_values()
        values.update(self._prepare_lab_dashboard_values())
        values["page_name"] = "lab_dashboard"
        return request.render("laboratory_management.portal_lab_dashboard", values)

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
    def portal_my_samples(self, page=1, sortby="date", filterby="all", **kwargs):
        domain, filterby = self._apply_filter_domain(self._sample_domain_for_current_user(), self._sample_filter_options(), filterby)
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
            url_args={"filterby": filterby},
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
                "filters": self._sample_filter_options(),
                "filterby": filterby,
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

        attachment = sample.sudo()._generate_report_pdf_attachment(force=False, suppress_error=True)
        pdf_content = attachment.raw or b""
        if not pdf_content:
            action_xmlid = sample.get_report_action_xmlid()
            action = request.env.ref(action_xmlid).sudo()
            pdf_content, _content_type = action._render_qweb_pdf(action.report_name, res_ids=sample.ids)
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
    def portal_my_test_requests(self, page=1, sortby="date", filterby="all", **kwargs):
        domain, filterby = self._apply_filter_domain(self._request_domain_for_current_user(), self._request_filter_options(), filterby)
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
            url_args={"filterby": filterby},
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
                "filters": self._request_filter_options(),
                "filterby": filterby,
            }
        )
        return request.render("laboratory_management.portal_my_lab_test_requests", values)

    @http.route("/my/lab/requests/new", type="http", auth="user", website=True, methods=["GET"])
    def portal_test_request_new_form(self, **kwargs):
        mixin = request.env["lab.master.data.mixin"].sudo()
        req_obj = request.env["lab.test.request"].sudo()
        partner = self._current_commercial_partner()
        portal_request_type = "institution" if self._is_professional_partner(partner) else "individual"
        request_type_map = dict(mixin._selection_request_type())
        services = (
            request.env["lab.service"]
            .sudo()
            .search(req_obj._allowed_service_domain_for_request_type(portal_request_type), order="name asc")
        )
        profiles = (
            request.env["lab.profile"]
            .sudo()
            .search(req_obj._allowed_profile_domain_for_request_type(portal_request_type), order="name asc")
        )
        dynamic_forms = (
            services.mapped("dynamic_form_rel_ids.form_id") | profiles.mapped("dynamic_form_rel_ids.form_id")
        ).filtered(lambda x: x.active and x.company_id in request.env.companies)
        dynamic_form_defs = {form.code: form.to_portal_schema() for form in dynamic_forms}
        physician_domain = [
            ("active", "=", True),
            ("company_id", "in", request.env.companies.ids),
            "|",
            ("institution_partner_id", "=", False),
            ("institution_partner_id", "child_of", partner.id),
        ]
        physicians = request.env["lab.physician"].sudo().search(physician_domain, order="name asc")
        physician_departments = (
            request.env["lab.physician.department"]
            .sudo()
            .search(
                [
                    ("id", "in", physicians.mapped("lab_physician_department_id").ids),
                    ("company_id", "in", request.env.companies.ids),
                    ("active", "=", True),
                ],
                order="sequence asc, name asc",
            )
        )
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "page_name": "lab_test_requests",
                "services": services,
                "profiles": profiles,
                "physicians": physicians,
                "physician_departments": physician_departments,
                "portal_request_type": portal_request_type,
                "portal_request_type_label": request_type_map.get(portal_request_type, portal_request_type),
                "priority_options": mixin._selection_priority(),
                "sample_type_options": mixin._selection_sample_type(),
                "dynamic_form_defs_json": json.dumps(dynamic_form_defs, ensure_ascii=False),
            }
        )
        return request.render("laboratory_management.portal_my_lab_test_request_new", values)

    @http.route("/my/lab/patient/lookup", type="http", auth="user", website=True, methods=["GET"])
    def portal_patient_lookup(self, **kwargs):
        identifier = (kwargs.get("identifier") or "").strip()
        payload = {"found": False}
        if not identifier:
            return request.make_response(
                json.dumps(payload),
                headers=[("Content-Type", "application/json")],
            )

        partner = self._current_commercial_partner()
        req = (
            request.env["lab.test.request"]
            .sudo()
            .search(
                [
                    ("patient_identifier", "=", identifier),
                    ("company_id", "in", request.env.companies.ids),
                    "|",
                    ("requester_partner_id", "child_of", partner.id),
                    ("client_partner_id", "child_of", partner.id),
                ],
                order="id desc",
                limit=1,
            )
        )
        if req:
            name = req.patient_name or (req.patient_id.name if req.patient_id else "") or ""
            phone = req.patient_phone or (req.patient_id.phone if req.patient_id else "") or ""
            payload = {
                "found": True,
                "patient_name": name,
                "patient_phone": phone,
                "patient_identifier": req.patient_identifier or identifier,
            }
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
        )

    @http.route("/my/lab/requests/new", type="http", auth="user", website=True, methods=["POST"])
    def portal_test_request_create(self, **post):
        partner = self._current_commercial_partner()
        mixin = request.env["lab.master.data.mixin"].sudo()
        req_obj = request.env["lab.test.request"].sudo()
        line_type = (post.get("line_type") or "service").strip()
        request_type = "institution" if self._is_professional_partner(partner) else "individual"
        priority = (post.get("priority") or mixin._default_priority_code()).strip()
        valid_priorities = {code for code, _label in mixin._selection_priority()}
        if priority not in valid_priorities:
            priority = mixin._default_priority_code()

        form = request.httprequest.form
        service_ids = [int(x) for x in form.getlist("service_ids") if str(x).strip().isdigit()]
        profile_ids = [int(x) for x in form.getlist("profile_ids") if str(x).strip().isdigit()]
        # Backward-compatible fallback for old single-select post.
        if not service_ids and str(post.get("service_id") or "").isdigit():
            service_ids = [int(post.get("service_id"))]
        if not profile_ids and str(post.get("profile_id") or "").isdigit():
            profile_ids = [int(post.get("profile_id"))]

        valid_sample_types = {code for code, _label in mixin._selection_sample_type()}
        allowed_catalog = req_obj._allowed_catalog_ids_for_request_type(request_type, company=request.env.company)
        allowed_service_ids = allowed_catalog["service_ids"]
        allowed_profile_ids = allowed_catalog["profile_ids"]

        specimen_payload_json = (post.get("specimen_payload_json") or "").strip()
        dynamic_form_payload_json = (post.get("dynamic_form_payload_json") or "").strip()
        has_specimen_payload = bool(specimen_payload_json)
        dynamic_form_payload = {}
        if dynamic_form_payload_json:
            try:
                dynamic_form_payload = json.loads(dynamic_form_payload_json)
            except Exception:
                return request.redirect("/my/lab/requests/new?error=dynamic_form_payload")

        if not has_specimen_payload and line_type == "service" and not service_ids:
            return request.redirect("/my/lab/requests/new?error=services")
        if not has_specimen_payload and line_type == "profile" and not profile_ids:
            return request.redirect("/my/lab/requests/new?error=profiles")

        line_note = (post.get("line_note") or "").strip()
        line_ids = []
        if has_specimen_payload:
            try:
                specimen_rows = json.loads(specimen_payload_json)
            except Exception:
                specimen_rows = []
            for row in specimen_rows:
                if not isinstance(row, dict):
                    continue
                specimen_ref = (row.get("specimen_ref") or "").strip() or "SP1"
                specimen_barcode = (row.get("specimen_barcode") or "").strip() or False
                specimen_type = (row.get("specimen_sample_type") or "").strip()
                if specimen_type not in valid_sample_types:
                    return request.redirect("/my/lab/requests/new?error=combination")
                row_type = (row.get("line_type") or "service").strip()
                row_note = (row.get("line_note") or line_note).strip()
                row_service_ids = self._normalize_id_list(row.get("service_ids"))
                row_profile_ids = self._normalize_id_list(row.get("profile_ids"))
                row_service_ids = [service_id for service_id in row_service_ids if service_id in allowed_service_ids]
                row_profile_ids = [profile_id for profile_id in row_profile_ids if profile_id in allowed_profile_ids]
                if row_type == "profile":
                    for profile_id in row_profile_ids:
                        line_ids.append(
                            (
                                0,
                                0,
                                {
                                    "line_type": "profile",
                                    "profile_id": profile_id,
                                    "quantity": 1,
                                    "note": row_note,
                                    "specimen_ref": specimen_ref,
                                    "specimen_barcode": specimen_barcode,
                                    "specimen_sample_type": specimen_type,
                                },
                            )
                        )
                else:
                    for service_id in row_service_ids:
                        line_ids.append(
                            (
                                0,
                                0,
                                {
                                    "line_type": "service",
                                    "service_id": service_id,
                                    "quantity": 1,
                                    "note": row_note,
                                    "specimen_ref": specimen_ref,
                                    "specimen_barcode": specimen_barcode,
                                    "specimen_sample_type": specimen_type,
                                },
                            )
                        )
            if not line_ids:
                return request.redirect("/my/lab/requests/new?error=combination")
        else:
            return request.redirect("/my/lab/requests/new?error=combination")

        selected_service_ids = []
        selected_profile_ids = []
        for _cmd, _unused, line_val in line_ids:
            if line_val.get("service_id"):
                selected_service_ids.append(line_val["service_id"])
            if line_val.get("profile_id"):
                selected_profile_ids.append(line_val["profile_id"])
        required_forms = (
            request.env["lab.service"].sudo().browse(list(set(selected_service_ids))).mapped("dynamic_form_rel_ids.form_id")
            | request.env["lab.profile"].sudo().browse(list(set(selected_profile_ids))).mapped("dynamic_form_rel_ids.form_id")
        ).filtered(lambda x: x.active and x.company_id in request.env.companies)
        try:
            req_obj.validate_dynamic_form_payload(required_forms, dynamic_form_payload)
        except Exception:
            return request.redirect("/my/lab/requests/new?error=dynamic_form_required")

        physician_partner = request.env["lab.physician"].browse()
        physician_department_id = int(post.get("physician_department_id") or 0)
        physician_partner_id = int(post.get("physician_partner_id") or 0)
        if physician_partner_id:
            physician_search_domain = [
                ("id", "=", physician_partner_id),
                ("active", "=", True),
                ("company_id", "in", request.env.companies.ids),
                "|",
                ("institution_partner_id", "=", False),
                ("institution_partner_id", "child_of", partner.id),
            ]
            if physician_department_id:
                physician_search_domain.append(("lab_physician_department_id", "=", physician_department_id))
            physician_partner = (
                request.env["lab.physician"]
                .sudo()
                .search(physician_search_domain, limit=1)
            )
            if not physician_partner:
                return request.redirect("/my/lab/requests/new?error=physician_department")

        client_partner_id = int(post.get("client_partner_id") or 0) or (partner.id if request_type == "institution" else False)
        institution_partner = request.env["res.partner"].sudo().browse(client_partner_id).exists() if client_partner_id else request.env["res.partner"]
        default_template = institution_partner.lab_default_report_template_id if institution_partner else request.env["lab.report.template"]
        if not default_template:
            default_template = request.env.ref("laboratory_management.report_template_classic", raise_if_not_found=False)

        values = {
            "requester_partner_id": partner.id,
            "request_type": request_type,
            "client_partner_id": client_partner_id,
            "patient_name": (post.get("patient_name") or "").strip(),
            "patient_identifier": (post.get("patient_identifier") or "").strip(),
            "patient_phone": (post.get("patient_phone") or "").strip(),
            "physician_partner_id": physician_partner.id or False,
            "physician_name": physician_partner.name or "",
            "clinical_note": (post.get("clinical_note") or "").strip(),
            "priority": priority,
            "company_id": request.env.company.id,
            "preferred_template_id": default_template.id or False,
            "line_ids": line_ids,
        }
        test_request = request.env["lab.test.request"].sudo().create(values)
        if dynamic_form_payload:
            try:
                test_request._apply_dynamic_form_payload(dynamic_form_payload, source="portal")
            except ValidationError:
                return request.redirect("/my/lab/requests/new?error=dynamic_form_required")
        attachments = self._extract_request_attachments_from_post()
        if attachments:
            test_request._create_request_attachments(attachments, source="portal")
        if post.get("submit_now") in ("on", "true", "1"):
            try:
                test_request.action_submit()
            except (ValidationError, UserError):
                return request.redirect("/my/lab/requests/new?error=dynamic_form_required")
        return request.redirect("/my/lab/requests/%s" % test_request.id)

    @http.route("/my/lab/requests/<int:request_id>", type="http", auth="user", website=True)
    def portal_test_request_detail(self, request_id, **kwargs):
        test_request = self._get_authorized_request(request_id)
        if not test_request:
            return request.redirect("/my/lab/requests")

        attachment_records = (
            request.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("res_model", "=", "lab.test.request"),
                    ("res_id", "=", test_request.id),
                    ("type", "=", "binary"),
                ],
                order="id desc",
            )
        )
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "record": test_request,
                "page_name": "lab_test_requests",
                "request_attachments": attachment_records,
            }
        )
        return request.render("laboratory_management.portal_my_lab_test_request_detail", values)

    @http.route(
        "/my/lab/requests/<int:request_id>/attachments/<int:attachment_id>/download",
        type="http",
        auth="user",
        website=True,
    )
    def portal_request_attachment_download(self, request_id, attachment_id, **kwargs):
        test_request = self._get_authorized_request(request_id)
        if not test_request:
            return request.redirect("/my/lab/requests")
        attachment = (
            request.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("id", "=", attachment_id),
                    ("res_model", "=", "lab.test.request"),
                    ("res_id", "=", test_request.id),
                    ("type", "=", "binary"),
                ],
                limit=1,
            )
        )
        if not attachment:
            return request.not_found()
        content = attachment.raw or b""
        headers = [
            ("Content-Type", attachment.mimetype or "application/octet-stream"),
            ("Content-Length", str(len(content))),
            ("Content-Disposition", f'attachment; filename="{attachment.name or "attachment"}"'),
        ]
        return request.make_response(content, headers=headers)

    @http.route("/my/lab/requests/<int:request_id>/submit", type="http", auth="user", website=True, methods=["POST"])
    def portal_test_request_submit(self, request_id, **kwargs):
        test_request = self._get_authorized_request(request_id)
        if not test_request:
            return request.redirect("/my/lab/requests")
        if test_request.state in ("draft", "cancelled"):
            test_request.sudo().action_submit()
        return request.redirect("/my/lab/requests/%s" % request_id)

    @http.route(["/my/lab/invoices", "/my/lab/invoices/page/<int:page>"], type="http", auth="user", website=True)
    def portal_my_request_invoices(self, page=1, sortby="date", filterby="all", **kwargs):
        domain, filterby = self._apply_filter_domain(self._request_invoice_domain_for_current_user(), self._invoice_filter_options(), filterby)
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
            url_args={"filterby": filterby},
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
                "filters": self._invoice_filter_options(),
                "filterby": filterby,
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
        pdf_content, _content_type = action._render_qweb_pdf(action.report_name, res_ids=batch.ids)
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
        pdf_content, _content_type = action._render_qweb_pdf(action.report_name, res_ids=record.ids)
        filename = f"Investigation-{record.name}.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf_content))),
            ("Content-Disposition", f'attachment; filename="{filename}"'),
        ]
        return request.make_response(pdf_content, headers=headers)
