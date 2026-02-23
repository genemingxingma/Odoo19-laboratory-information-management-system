import json

from odoo import fields, http
from odoo.http import request


class LaboratoryExternalApi(http.Controller):
    def _authorize_endpoint(self, endpoint):
        auth_type = endpoint.auth_type or "none"
        headers = request.httprequest.headers
        if auth_type == "none":
            return True
        if auth_type == "bearer":
            auth = headers.get("Authorization", "")
            expected = "Bearer %s" % (endpoint.token or "")
            return bool(endpoint.token and auth == expected)
        if auth_type == "api_key":
            return bool(endpoint.api_key and headers.get("X-API-Key") == endpoint.api_key)
        if auth_type == "basic":
            auth = headers.get("Authorization", "")
            if not auth.startswith("Basic "):
                return False
            try:
                import base64

                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
            except Exception:  # noqa: BLE001
                return False
            if ":" not in decoded:
                return False
            username, password = decoded.split(":", 1)
            return bool(username == (endpoint.username or "") and password == (endpoint.password or ""))
        return False

    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json; charset=utf-8")],
            status=status,
        )

    def _lookup_endpoint(self, endpoint_code):
        endpoint = (
            request.env["lab.interface.endpoint"]
            .sudo()
            .search([("code", "=", endpoint_code), ("active", "=", True), ("external_api_enabled", "=", True)], limit=1)
        )
        if not endpoint:
            return None, self._json_response({"ok": False, "error": "endpoint_not_found"}, status=404)
        if endpoint.protocol != "rest":
            return None, self._json_response({"ok": False, "error": "endpoint_protocol_not_rest"}, status=403)
        if not self._authorize_endpoint(endpoint):
            return None, self._json_response({"ok": False, "error": "unauthorized"}, status=401)
        return endpoint, None

    def _request_domain_for_endpoint(self, endpoint):
        domain = [("company_id", "=", endpoint.external_company_id.id)]
        partner = endpoint.get_external_api_partner()
        if partner:
            domain += [
                "|",
                ("requester_partner_id", "child_of", partner.id),
                ("client_partner_id", "child_of", partner.id),
            ]
        return domain

    def _sample_domain_for_endpoint(self, endpoint):
        domain = [("company_id", "=", endpoint.external_company_id.id)]
        partner = endpoint.get_external_api_partner()
        if partner:
            domain += [
                "|",
                ("patient_id", "child_of", partner.id),
                ("client_id", "child_of", partner.id),
            ]
        return domain

    def _prepare_request_payload(self, rec):
        return {
            "id": rec.id,
            "request_no": rec.name,
            "state": rec.state,
            "request_type": rec.request_type,
            "requester": rec.requester_partner_id.name,
            "institution": rec.client_partner_id.name if rec.client_partner_id else "",
            "patient": {
                "id": rec.patient_id.id if rec.patient_id else False,
                "name": rec.patient_name or (rec.patient_id.name if rec.patient_id else ""),
                "identifier": rec.patient_identifier or "",
                "gender": rec.patient_gender or "",
                "phone": rec.patient_phone or "",
            },
            "priority": rec.priority,
            "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
            "approved_at": rec.approved_at.isoformat() if rec.approved_at else None,
            "completed_at": rec.completed_at.isoformat() if rec.completed_at else None,
            "samples": [
                {
                    "sample_id": s.id,
                    "accession": s.name,
                    "barcode": s.accession_barcode or "",
                    "state": s.state,
                    "report_date": s.report_date.isoformat() if s.report_date else None,
                }
                for s in rec.sample_ids
            ],
        }

    def _check_metadata_access(self, endpoint):
        if not endpoint.external_allow_metadata_query:
            return self._json_response({"ok": False, "error": "metadata_query_disabled"}, status=403)
        return False

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/requests",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def external_request_create(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return {"ok": False, "error": "endpoint_error"}
        if not endpoint.external_allow_request_push:
            return {"ok": False, "error": "request_push_disabled"}

        body = kwargs.get("params") if isinstance(kwargs.get("params"), dict) else kwargs or {}
        external_uid = (body.get("external_uid") or "").strip()
        patient = body.get("patient") or {}
        physician = body.get("physician") or {}
        lines = body.get("lines") or []
        if not lines:
            return {"ok": False, "error": "lines_required"}

        request_obj = request.env["lab.test.request"].sudo().with_company(endpoint.external_company_id)
        service_obj = request.env["lab.service"].sudo().with_company(endpoint.external_company_id)
        profile_obj = request.env["lab.profile"].sudo().with_company(endpoint.external_company_id)
        partner_obj = request.env["res.partner"].sudo().with_company(endpoint.external_company_id)
        template_obj = request.env["lab.report.template"].sudo().with_company(endpoint.external_company_id)

        if external_uid:
            existing = request_obj.search(
                [
                    ("external_endpoint_id", "=", endpoint.id),
                    ("external_request_uid", "=", external_uid),
                ],
                limit=1,
            )
            if existing:
                return {"ok": True, "deduplicated": True, "request": self._prepare_request_payload(existing)}

        partner = endpoint.get_external_api_partner()
        requester = partner or request.env.user.partner_id
        client_partner = partner if (partner and partner.is_company) else False

        preferred_template = False
        template_code = (body.get("preferred_template_code") or "").strip()
        if template_code:
            preferred_template = template_obj.search([("code", "=", template_code)], limit=1)

        physician_partner = False
        physician_code = (physician.get("partner_ref") or "").strip()
        if physician_code:
            physician_partner = partner_obj.search([("ref", "=", physician_code)], limit=1)

        valid_sample_types = {code for code, _label in request_obj._selection_sample_type()}
        line_vals = []
        for index, line in enumerate(lines, start=1):
            line_type = line.get("line_type") or "service"
            if line_type not in ("service", "profile"):
                return {"ok": False, "error": "invalid_line_type"}
            specimen_sample_type = (line.get("specimen_sample_type") or "").strip()
            if not specimen_sample_type:
                return {"ok": False, "error": "specimen_sample_type_required", "line_index": index}
            if specimen_sample_type not in valid_sample_types:
                return {
                    "ok": False,
                    "error": "invalid_specimen_sample_type",
                    "line_index": index,
                    "specimen_sample_type": specimen_sample_type,
                }
            vals = {
                "line_type": line_type,
                "quantity": 1,
                "specimen_ref": (line.get("specimen_ref") or "SP1").strip() or "SP1",
                "specimen_barcode": (line.get("specimen_barcode") or "").strip(),
                "specimen_sample_type": specimen_sample_type,
                "note": line.get("note") or "",
            }
            if line_type == "service":
                code = (line.get("service_code") or "").strip()
                service = service_obj.search([("code", "=", code)], limit=1)
                if not service:
                    return {"ok": False, "error": "service_not_found", "service_code": code}
                vals["service_id"] = service.id
            else:
                code = (line.get("profile_code") or "").strip()
                profile = profile_obj.search([("code", "=", code)], limit=1)
                if not profile:
                    return {"ok": False, "error": "profile_not_found", "profile_code": code}
                vals["profile_id"] = profile.id
            line_vals.append((0, 0, vals))

        request_vals = {
            "requester_partner_id": requester.id,
            "request_type": "institution" if client_partner else "individual",
            "client_partner_id": client_partner.id if client_partner else False,
            "patient_name": (patient.get("name") or "").strip() or "Unknown",
            "patient_identifier": (patient.get("identifier") or "").strip() or False,
            "patient_gender": patient.get("gender") or "unknown",
            "patient_phone": (patient.get("phone") or "").strip() or False,
            "patient_birthdate": patient.get("birthdate") or False,
            "physician_partner_id": physician_partner.id if physician_partner else False,
            "physician_name": (physician.get("name") or "").strip() or False,
            "requested_collection_date": body.get("requested_collection_date") or fields.Datetime.now(),
            "priority": body.get("priority") or "routine",
            "clinical_note": body.get("clinical_note") or False,
            "preferred_template_id": preferred_template.id if preferred_template else False,
            "line_ids": line_vals,
            "company_id": endpoint.external_company_id.id,
            "external_endpoint_id": endpoint.id,
            "external_request_uid": external_uid or False,
        }
        req = request_obj.create(request_vals)
        if endpoint.external_auto_submit_request:
            req.action_submit()
        return {"ok": True, "request": self._prepare_request_payload(req)}

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/requests/<string:request_no>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_request_query(self, endpoint_code, request_no, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        if not endpoint.external_allow_result_query:
            return self._json_response({"ok": False, "error": "result_query_disabled"}, status=403)
        domain = [("name", "=", request_no)] + self._request_domain_for_endpoint(endpoint)
        rec = request.env["lab.test.request"].sudo().search(domain, limit=1)
        if not rec:
            return self._json_response({"ok": False, "error": "request_not_found"}, status=404)
        return self._json_response({"ok": True, "request": self._prepare_request_payload(rec)})

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/samples/<string:accession>/results",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_sample_results(self, endpoint_code, accession, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        if not endpoint.external_allow_result_query:
            return self._json_response({"ok": False, "error": "result_query_disabled"}, status=403)
        domain = [("name", "=", accession)] + self._sample_domain_for_endpoint(endpoint)
        sample = request.env["lab.sample"].sudo().search(domain, limit=1)
        if not sample:
            return self._json_response({"ok": False, "error": "sample_not_found"}, status=404)
        payload = {
            "ok": True,
            "sample": {
                "id": sample.id,
                "accession": sample.name,
                "barcode": sample.accession_barcode or "",
                "state": sample.state,
                "report_date": sample.report_date.isoformat() if sample.report_date else None,
                "patient": sample.patient_id.name,
                "request_no": sample.request_id.name if sample.request_id else "",
                "results": [
                    {
                        "service_code": line.service_id.code,
                        "service_name": line.service_id.name,
                        "result_value": line.result_value or "",
                        "binary_interpretation": line.binary_interpretation or "",
                        "state": line.state,
                        "unit": line.service_id.unit or "",
                        "ref_min": line.service_id.ref_min,
                        "ref_max": line.service_id.ref_max,
                    }
                    for line in sample.analysis_ids
                ],
                "ai_interpretation": sample.ai_interpretation_text if sample.ai_portal_visible else "",
            },
        }
        return self._json_response(payload)

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/samples/<string:accession>/report/pdf",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_sample_report_pdf(self, endpoint_code, accession, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        if not endpoint.external_allow_report_download:
            return self._json_response({"ok": False, "error": "report_download_disabled"}, status=403)
        domain = [("name", "=", accession)] + self._sample_domain_for_endpoint(endpoint)
        sample = request.env["lab.sample"].sudo().search(domain, limit=1)
        if not sample:
            return self._json_response({"ok": False, "error": "sample_not_found"}, status=404)
        if sample.state not in ("verified", "reported"):
            return self._json_response({"ok": False, "error": "report_not_ready"}, status=409)

        attachment = sample.sudo()._generate_report_pdf_attachment(force=False, suppress_error=True)
        pdf_content = attachment.raw or b""
        if not pdf_content:
            action_xmlid = sample.get_report_action_xmlid()
            action = request.env.ref(action_xmlid).sudo()
            pdf_content, _content_type = action._render_qweb_pdf(action.report_name, res_ids=sample.ids)
        filename = "%s.pdf" % (sample.name or "report")
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", str(len(pdf_content))),
            ("Content-Disposition", 'attachment; filename="%s"' % filename),
        ]
        return request.make_response(pdf_content, headers=headers)

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/meta/sample_types",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_meta_sample_types(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        deny = self._check_metadata_access(endpoint)
        if deny:
            return deny
        recs = (
            request.env["lab.sample.type"]
            .sudo()
            .with_company(endpoint.external_company_id)
            .search([("active", "=", True)], order="sequence asc, id asc")
        )
        return self._json_response(
            {
                "ok": True,
                "sample_types": [
                    {
                        "code": rec.code,
                        "name": rec.name,
                        "is_default": bool(rec.is_default),
                    }
                    for rec in recs
                ],
            }
        )

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/meta/services",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_meta_services(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        deny = self._check_metadata_access(endpoint)
        if deny:
            return deny
        domain = [("active", "=", True), ("company_id", "=", endpoint.external_company_id.id)]
        recs = request.env["lab.service"].sudo().with_company(endpoint.external_company_id).search(domain, order="code asc, id asc")
        return self._json_response(
            {
                "ok": True,
                "services": [
                    {
                        "code": rec.code,
                        "name": rec.name,
                        "sample_type": rec.sample_type or "",
                    }
                    for rec in recs
                ],
            }
        )

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/meta/profiles",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def external_meta_profiles(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        deny = self._check_metadata_access(endpoint)
        if deny:
            return deny
        domain = [("active", "=", True), ("company_id", "=", endpoint.external_company_id.id)]
        recs = request.env["lab.profile"].sudo().with_company(endpoint.external_company_id).search(domain, order="code asc, id asc")
        return self._json_response(
            {
                "ok": True,
                "profiles": [
                    {
                        "code": rec.code,
                        "name": rec.name,
                        "sample_type": getattr(rec, "sample_type", "") or "",
                    }
                    for rec in recs
                ],
            }
        )
