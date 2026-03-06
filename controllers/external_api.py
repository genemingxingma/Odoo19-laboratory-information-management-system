import base64
import binascii
import json
import os

from odoo import fields, http
from odoo.http import request


class LaboratoryExternalApi(http.Controller):
    _MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

    def _to_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            val = value.strip().lower()
            if val in {"1", "true", "yes", "y", "on"}:
                return True
            if val in {"0", "false", "no", "n", "off"}:
                return False
        return False

    def _to_int(self, value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    def _resolve_country(self, payload):
        country_obj = request.env["res.country"].sudo()
        country_id = self._to_int(payload.get("country_id"))
        if country_id:
            country = country_obj.browse(country_id).exists()
            if country:
                return country
        country_code = (payload.get("country_code") or "").strip()
        if country_code:
            country = country_obj.search([("code", "=", country_code.upper())], limit=1)
            if country:
                return country
        country_name = (payload.get("country") or "").strip()
        if country_name:
            return country_obj.search([("name", "ilike", country_name)], limit=1)
        return country_obj.browse()

    def _resolve_state(self, payload, country=False):
        state_obj = request.env["res.country.state"].sudo()
        state_id = self._to_int(payload.get("state_id"))
        if state_id:
            state = state_obj.browse(state_id).exists()
            if state and (not country or state.country_id == country):
                return state
        state_code = (payload.get("state_code") or "").strip()
        if state_code:
            domain = [("code", "=", state_code.upper())]
            if country:
                domain.append(("country_id", "=", country.id))
            state = state_obj.search(domain, limit=1)
            if state:
                return state
        state_name = (payload.get("state") or "").strip()
        if state_name:
            domain = [("name", "ilike", state_name)]
            if country:
                domain.append(("country_id", "=", country.id))
            return state_obj.search(domain, limit=1)
        return state_obj.browse()

    def _find_or_create_patient(self, payload, company):
        patient_obj = request.env["lab.patient"].sudo().with_company(company)
        patient_id = self._to_int(payload.get("id") or payload.get("patient_id"))
        if patient_id:
            patient = patient_obj.browse(patient_id).exists()
            if patient and patient.company_id == company:
                return patient

        identifier = (payload.get("identifier") or payload.get("patient_id_no") or payload.get("id_no") or "").strip()
        passport_no = (payload.get("passport_no") or payload.get("passport") or "").strip()
        name = (payload.get("name") or "").strip()
        phone = (payload.get("phone") or "").strip()
        gender = payload.get("gender") or "unknown"
        birthdate = payload.get("birthdate") or False

        patient = patient_obj.browse()
        if identifier:
            patient = patient_obj.search(
                [
                    ("company_id", "=", company.id),
                    ("identifier", "=", identifier),
                ],
                limit=1,
            )
        if not patient and passport_no:
            patient = patient_obj.search(
                [
                    ("company_id", "=", company.id),
                    ("passport_no", "=", passport_no),
                ],
                limit=1,
            )
        if not patient and name and phone:
            patient = patient_obj.search(
                [
                    ("company_id", "=", company.id),
                    ("name", "=", name),
                    ("phone", "=", phone),
                ],
                limit=1,
            )

        country = self._resolve_country(payload)
        state = self._resolve_state(payload, country=country)
        vals = {
            "company_id": company.id,
            "name": name or "Unknown",
            "identifier": identifier or False,
            "passport_no": passport_no or False,
            "birthdate": birthdate or False,
            "gender": gender if gender in {"male", "female", "other", "unknown"} else "unknown",
            "phone": phone or False,
            "email": (payload.get("email") or "").strip() or False,
            "lang": (payload.get("lang") or "").strip() or False,
            "street": (payload.get("street") or "").strip() or False,
            "street2": (payload.get("street2") or "").strip() or False,
            "city": (payload.get("city") or "").strip() or False,
            "zip": (payload.get("zip") or "").strip() or False,
            "country_id": country.id if country else False,
            "state_id": state.id if state else False,
            "emergency_contact_name": (payload.get("emergency_contact_name") or "").strip() or False,
            "emergency_contact_phone": (payload.get("emergency_contact_phone") or "").strip() or False,
            "emergency_contact_relation": (payload.get("emergency_contact_relation") or "").strip() or False,
            "allergy_history": payload.get("allergy_history") or False,
            "past_medical_history": payload.get("past_medical_history") or False,
            "medication_history": payload.get("medication_history") or False,
            "pregnancy_status": payload.get("pregnancy_status")
            if payload.get("pregnancy_status") in {"not_applicable", "pregnant", "not_pregnant", "unknown"}
            else "not_applicable",
            "breastfeeding": self._to_bool(payload.get("breastfeeding")),
            "insurance_provider": (payload.get("insurance_provider") or "").strip() or False,
            "insurance_no": (payload.get("insurance_no") or "").strip() or False,
            "informed_consent_signed": self._to_bool(payload.get("informed_consent_signed")),
            "informed_consent_date": payload.get("informed_consent_date") or False,
            "note": payload.get("note") or False,
        }

        if patient:
            write_vals = {k: v for k, v in vals.items() if v not in (False, "", None)}
            if write_vals:
                patient.write(write_vals)
            return patient

        if not any([name, identifier, passport_no]):
            return patient_obj.browse()
        return patient_obj.create(vals)

    def _find_or_create_physician(self, payload, company):
        physician_obj = request.env["lab.physician"].sudo().with_company(company)
        dep_obj = request.env["lab.physician.department"].sudo().with_company(company)
        partner_obj = request.env["res.partner"].sudo().with_company(company)

        physician_id = self._to_int(payload.get("id") or payload.get("physician_id"))
        if physician_id:
            physician = physician_obj.browse(physician_id).exists()
            if physician and physician.company_id == company:
                return physician

        code = (payload.get("code") or payload.get("partner_ref") or "").strip()
        license_no = (payload.get("license_no") or "").strip()
        name = (payload.get("name") or "").strip()
        phone = (payload.get("phone") or "").strip()

        physician = physician_obj.browse()
        if code:
            physician = physician_obj.search([("company_id", "=", company.id), ("code", "=", code)], limit=1)
        if not physician and license_no:
            physician = physician_obj.search([("company_id", "=", company.id), ("license_no", "=", license_no)], limit=1)
        if not physician and name and phone:
            physician = physician_obj.search([("company_id", "=", company.id), ("name", "=", name), ("phone", "=", phone)], limit=1)

        dept = dep_obj.browse()
        dept_id = self._to_int(payload.get("department_id"))
        if dept_id:
            dept = dep_obj.browse(dept_id).exists()
        if not dept:
            dept_code = (payload.get("department_code") or "").strip()
            if dept_code:
                dept = dep_obj.search([("company_id", "=", company.id), ("code", "=", dept_code)], limit=1)

        institution = partner_obj.browse()
        institution_id = self._to_int(payload.get("institution_id"))
        if institution_id:
            institution = partner_obj.browse(institution_id).exists()
        if not institution:
            institution_ref = (payload.get("institution_ref") or "").strip()
            if institution_ref:
                institution = partner_obj.search(
                    [
                        "|",
                        ("ref", "=", institution_ref),
                        ("vat", "=", institution_ref),
                    ],
                    limit=1,
                )
        if not institution:
            institution_name = (payload.get("institution_name") or "").strip()
            if institution_name:
                institution = partner_obj.search([("name", "=", institution_name)], limit=1)

        vals = {
            "company_id": company.id,
            "name": name or (code or license_no or "Unknown Physician"),
            "code": code or False,
            "license_no": license_no or False,
            "title": (payload.get("title") or "").strip() or False,
            "specialty": (payload.get("specialty") or "").strip() or False,
            "phone": phone or False,
            "email": (payload.get("email") or "").strip() or False,
            "institution_partner_id": institution.id if institution else False,
            "lab_physician_department_id": dept.id if dept else False,
            "notify_by_email": self._to_bool(payload.get("notify_by_email", True)),
            "notify_by_sms": self._to_bool(payload.get("notify_by_sms")),
            "note": payload.get("note") or False,
        }

        if physician:
            write_vals = {k: v for k, v in vals.items() if v not in (False, "", None)}
            if write_vals:
                physician.write(write_vals)
            return physician

        if not any([name, code, license_no]):
            return physician_obj.browse()
        return physician_obj.create(vals)

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

    def _lookup_endpoint(self, endpoint_code, allowed_protocols=("rest",)):
        endpoint = (
            request.env["lab.interface.endpoint"]
            .sudo()
            .search([("code", "=", endpoint_code), ("active", "=", True), ("external_api_enabled", "=", True)], limit=1)
        )
        if not endpoint:
            return None, self._json_response({"ok": False, "error": "endpoint_not_found"}, status=404)
        if allowed_protocols and endpoint.protocol not in allowed_protocols:
            return None, self._json_response(
                {"ok": False, "error": "endpoint_protocol_not_allowed", "allowed_protocols": list(allowed_protocols)},
                status=403,
            )
        if not self._authorize_endpoint(endpoint):
            return None, self._json_response({"ok": False, "error": "unauthorized"}, status=401)
        return endpoint, None

    def _ingest_result_payload(self, endpoint, payload, *, external_uid=False, raw_message=False, source_ip=False):
        if not endpoint.external_allow_result_push:
            return None, self._json_response({"ok": False, "error": "result_push_disabled"}, status=403)
        if endpoint.direction not in ("inbound", "bidirectional"):
            return None, self._json_response({"ok": False, "error": "direction_not_allowed"}, status=403)
        accession = (payload.get("accession") or "").strip()
        results = payload.get("results") or []
        if not accession:
            return None, self._json_response({"ok": False, "error": "accession_required"}, status=400)
        if not isinstance(results, list) or not results:
            return None, self._json_response({"ok": False, "error": "results_required"}, status=400)
        try:
            job = endpoint.ingest_message(
                message_type="result",
                payload=payload,
                external_uid=external_uid,
                source_ip=source_ip,
                raw_message=raw_message,
            )
        except Exception as err:  # noqa: BLE001
            return None, self._json_response({"ok": False, "error": "ingest_failed", "detail": str(err)}, status=400)
        return job, None

    def _parse_http_json_body(self):
        try:
            return json.loads((request.httprequest.data or b"{}").decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None

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
                ("request_id.requester_partner_id", "child_of", partner.id),
                ("client_id", "child_of", partner.id),
            ]
        return domain

    def _prepare_request_payload(self, rec):
        attachment_recs = (
            request.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("res_model", "=", "lab.test.request"),
                    ("res_id", "=", rec.id),
                    ("type", "=", "binary"),
                ],
                order="id asc",
            )
        )
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
                "passport_no": rec.patient_id.passport_no if rec.patient_id else "",
                "gender": rec.patient_gender or "",
                "birthdate": rec.patient_birthdate.isoformat() if rec.patient_birthdate else None,
                "age_display": rec.patient_id.age_display if rec.patient_id else "",
                "phone": rec.patient_phone or "",
                "email": rec.patient_id.email if rec.patient_id else "",
                "lang": rec.patient_id.lang if rec.patient_id else "",
                "address": {
                    "street": rec.patient_id.street if rec.patient_id else "",
                    "street2": rec.patient_id.street2 if rec.patient_id else "",
                    "city": rec.patient_id.city if rec.patient_id else "",
                    "state_code": rec.patient_id.state_id.code if rec.patient_id and rec.patient_id.state_id else "",
                    "state": rec.patient_id.state_id.name if rec.patient_id and rec.patient_id.state_id else "",
                    "zip": rec.patient_id.zip if rec.patient_id else "",
                    "country_code": rec.patient_id.country_id.code if rec.patient_id and rec.patient_id.country_id else "",
                    "country": rec.patient_id.country_id.name if rec.patient_id and rec.patient_id.country_id else "",
                },
                "emergency_contact": {
                    "name": rec.patient_id.emergency_contact_name if rec.patient_id else "",
                    "phone": rec.patient_id.emergency_contact_phone if rec.patient_id else "",
                    "relation": rec.patient_id.emergency_contact_relation if rec.patient_id else "",
                },
            },
            "physician": {
                "id": rec.physician_partner_id.id if rec.physician_partner_id else False,
                "name": rec.physician_name or (rec.physician_partner_id.name if rec.physician_partner_id else ""),
                "code": rec.physician_partner_id.code if rec.physician_partner_id else "",
                "license_no": rec.physician_partner_id.license_no if rec.physician_partner_id else "",
                "title": rec.physician_partner_id.title if rec.physician_partner_id else "",
                "specialty": rec.physician_partner_id.specialty if rec.physician_partner_id else "",
                "phone": rec.physician_partner_id.phone if rec.physician_partner_id else "",
                "email": rec.physician_partner_id.email if rec.physician_partner_id else "",
                "department": {
                    "id": rec.physician_partner_id.lab_physician_department_id.id if rec.physician_partner_id and rec.physician_partner_id.lab_physician_department_id else False,
                    "code": rec.physician_partner_id.lab_physician_department_id.code if rec.physician_partner_id and rec.physician_partner_id.lab_physician_department_id else "",
                    "name": rec.physician_partner_id.lab_physician_department_id.name if rec.physician_partner_id and rec.physician_partner_id.lab_physician_department_id else "",
                },
                "institution": {
                    "id": rec.physician_partner_id.institution_partner_id.id if rec.physician_partner_id and rec.physician_partner_id.institution_partner_id else False,
                    "name": rec.physician_partner_id.institution_partner_id.name if rec.physician_partner_id and rec.physician_partner_id.institution_partner_id else "",
                },
                "notify_by_email": bool(rec.physician_partner_id.notify_by_email) if rec.physician_partner_id else False,
                "notify_by_sms": bool(rec.physician_partner_id.notify_by_sms) if rec.physician_partner_id else False,
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
            "attachments": [
                {
                    "id": att.id,
                    "name": att.name,
                    "mimetype": att.mimetype or "",
                    "size": att.file_size or 0,
                }
                for att in attachment_recs
            ],
        }

    def _normalize_api_attachments(self, attachments):
        normalized = []
        for index, item in enumerate(attachments or [], start=1):
            if not isinstance(item, dict):
                return None, {"ok": False, "error": "invalid_attachment_payload", "attachment_index": index}
            name = os.path.basename((item.get("name") or item.get("filename") or "").strip())
            data_b64 = (item.get("content_base64") or item.get("datas") or "").strip()
            if not name or not data_b64:
                return None, {"ok": False, "error": "attachment_name_or_data_missing", "attachment_index": index}
            try:
                content = base64.b64decode(data_b64, validate=True)
            except (binascii.Error, ValueError):
                return None, {"ok": False, "error": "attachment_decode_failed", "attachment_index": index}
            if len(content) > self._MAX_ATTACHMENT_BYTES:
                return None, {
                    "ok": False,
                    "error": "attachment_too_large",
                    "attachment_index": index,
                    "max_bytes": self._MAX_ATTACHMENT_BYTES,
                }
            normalized.append(
                {
                    "name": name,
                    "content": content,
                    "mimetype": (item.get("mimetype") or "application/octet-stream").strip(),
                }
            )
        return normalized, None

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
        attachments_payload = body.get("attachments") or []
        dynamic_forms_payload = body.get("dynamic_forms") or {}
        if not lines:
            return {"ok": False, "error": "lines_required"}

        request_obj = request.env["lab.test.request"].sudo().with_company(endpoint.external_company_id)
        service_obj = request.env["lab.service"].sudo().with_company(endpoint.external_company_id)
        profile_obj = request.env["lab.profile"].sudo().with_company(endpoint.external_company_id)
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

        patient_record = self._find_or_create_patient(patient, endpoint.external_company_id)
        physician_partner = self._find_or_create_physician(physician, endpoint.external_company_id)

        valid_sample_types = {code for code, _label in request_obj._selection_sample_type()}
        request_type = "institution" if client_partner else "individual"
        allowed_catalog = request_obj._allowed_catalog_ids_for_request_type(
            request_type,
            company=endpoint.external_company_id,
        )
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
                service = service_obj.search(
                    [
                        ("code", "=", code),
                        ("active", "=", True),
                        ("profile_only", "=", False),
                    ],
                    limit=1,
                )
                if not service:
                    return {"ok": False, "error": "service_not_found", "service_code": code}
                if service.id not in allowed_catalog["service_ids"]:
                    return {"ok": False, "error": "service_not_allowed_for_request_type", "service_code": code}
                vals["service_id"] = service.id
            else:
                code = (line.get("profile_code") or "").strip()
                profile = profile_obj.search([("code", "=", code)], limit=1)
                if not profile:
                    return {"ok": False, "error": "profile_not_found", "profile_code": code}
                if profile.id not in allowed_catalog["profile_ids"]:
                    return {"ok": False, "error": "profile_not_allowed_for_request_type", "profile_code": code}
                vals["profile_id"] = profile.id
            line_vals.append((0, 0, vals))

        required_forms = (
            service_obj.browse([vals[2]["service_id"] for vals in line_vals if vals[2].get("service_id")]).mapped("dynamic_form_rel_ids.form_id")
            | profile_obj.browse([vals[2]["profile_id"] for vals in line_vals if vals[2].get("profile_id")]).mapped("dynamic_form_rel_ids.form_id")
        ).filtered(lambda x: x.active and x.company_id == endpoint.external_company_id)
        try:
            request_obj.validate_dynamic_form_payload(required_forms, dynamic_forms_payload)
        except Exception as exc:
            return {"ok": False, "error": "dynamic_form_required", "detail": str(exc)}
        normalized_attachments = []
        if attachments_payload:
            normalized_attachments, attachment_error = self._normalize_api_attachments(attachments_payload)
            if attachment_error:
                return attachment_error

        request_vals = {
            "requester_partner_id": requester.id,
            "request_type": request_type,
            "client_partner_id": client_partner.id if client_partner else False,
            "patient_id": patient_record.id if patient_record else False,
            "patient_name": (patient.get("name") or (patient_record.name if patient_record else "")).strip() or "Unknown",
            "patient_identifier": (patient.get("identifier") or patient.get("patient_id_no") or patient.get("id_no") or (patient_record.identifier if patient_record else "")).strip() or False,
            "patient_gender": (patient.get("gender") or (patient_record.gender if patient_record else "unknown")) or "unknown",
            "patient_phone": (patient.get("phone") or (patient_record.phone if patient_record else "")).strip() or False,
            "patient_birthdate": patient.get("birthdate") or (patient_record.birthdate if patient_record else False),
            "physician_partner_id": physician_partner.id if physician_partner else False,
            "physician_name": (physician.get("name") or (physician_partner.name if physician_partner else "")).strip() or False,
            "requested_collection_date": body.get("requested_collection_date") or fields.Datetime.now(),
            "priority": body.get("priority") or "routine",
            "clinical_note": body.get("clinical_note") or False,
            "preferred_template_id": preferred_template.id if preferred_template else False,
            "line_ids": line_vals,
            "company_id": endpoint.external_company_id.id,
            "external_endpoint_id": endpoint.id,
            "external_request_uid": external_uid or False,
        }
        try:
            with request.env.cr.savepoint():
                req = request_obj.create(request_vals)
                if dynamic_forms_payload:
                    req._apply_dynamic_form_payload(dynamic_forms_payload, source="api")
                if normalized_attachments:
                    req._create_request_attachments(normalized_attachments, source="external_api")
                if endpoint.external_auto_submit_request:
                    req.action_submit()
        except Exception as exc:
            return {"ok": False, "error": "request_create_failed", "detail": str(exc)}
        return {"ok": True, "request": self._prepare_request_payload(req)}

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/results",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def external_result_push(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code, allowed_protocols=("rest",))
        if error:
            return error
        body = self._parse_http_json_body()
        if body is None:
            return self._json_response({"ok": False, "error": "invalid_json"}, status=400)
        payload = {
            "accession": (body.get("accession") or "").strip(),
            "results": body.get("results") or [],
        }
        if body.get("meta"):
            payload["meta"] = body.get("meta")
        external_uid = (body.get("external_uid") or "").strip() or False
        job, ingest_error = self._ingest_result_payload(
            endpoint,
            payload,
            external_uid=external_uid,
            raw_message=False,
            source_ip=request.httprequest.remote_addr or "",
        )
        if ingest_error:
            return ingest_error
        return self._json_response(
            {
                "ok": job.state == "done",
                "ack_code": job.ack_code or ("AA" if job.state == "done" else "AE"),
                "job_id": job.id,
                "job_name": job.name,
                "state": job.state,
                "error": job.error_message or "",
            }
        )

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/samples/<string:accession>/results",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def external_sample_result_push(self, endpoint_code, accession, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code, allowed_protocols=("rest",))
        if error:
            return error
        body = self._parse_http_json_body()
        if body is None:
            return self._json_response({"ok": False, "error": "invalid_json"}, status=400)
        payload = {
            "accession": accession,
            "results": body.get("results") or [],
        }
        if body.get("meta"):
            payload["meta"] = body.get("meta")
        external_uid = (body.get("external_uid") or "").strip() or False
        job, ingest_error = self._ingest_result_payload(
            endpoint,
            payload,
            external_uid=external_uid,
            raw_message=False,
            source_ip=request.httprequest.remote_addr or "",
        )
        if ingest_error:
            return ingest_error
        return self._json_response(
            {
                "ok": job.state == "done",
                "ack_code": job.ack_code or ("AA" if job.state == "done" else "AE"),
                "job_id": job.id,
                "job_name": job.name,
                "state": job.state,
                "error": job.error_message or "",
            }
        )

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/hl7/oru",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def external_hl7_oru_push(self, endpoint_code, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code, allowed_protocols=("hl7v2",))
        if error:
            return error
        if not endpoint.external_allow_result_push:
            return request.make_response("result_push_disabled", status=403)
        if endpoint.direction not in ("inbound", "bidirectional"):
            return request.make_response("direction_not_allowed", status=403)

        adapter = request.env["lab.protocol.adapter"].sudo()
        raw = request.httprequest.get_data(as_text=True) or ""
        if not raw.strip():
            return request.make_response("hl7_payload_required", status=400)

        schema = {}
        try:
            schema = json.loads(endpoint.mapping_schema or "{}")
        except Exception:  # noqa: BLE001
            schema = {}
        try:
            parsed = adapter.parse_hl7_message(raw, field_map=(schema.get("hl7_field_map") or {}))
            message_type = parsed.get("message_type") or "result"
            if message_type not in ("result", "report"):
                ack = adapter.build_hl7_ack("AR", (parsed.get("meta") or {}).get("control_id"), "only_result_or_report")
                return request.make_response(ack, headers=[("Content-Type", "text/plain; charset=utf-8")], status=400)
            payload = parsed.get("payload") or {}
            external_uid = parsed.get("external_uid")
            job = endpoint.ingest_message(
                message_type=message_type,
                payload=payload,
                external_uid=external_uid,
                source_ip=request.httprequest.remote_addr or "",
                raw_message=raw,
            )
            ack = adapter.build_hl7_ack(
                job.ack_code or ("AA" if job.state == "done" else "AE"),
                (parsed.get("meta") or {}).get("control_id"),
                job.error_message or "",
            )
            return request.make_response(ack, headers=[("Content-Type", "text/plain; charset=utf-8")], status=200)
        except Exception as err:  # noqa: BLE001
            ack = adapter.build_hl7_ack("AR", "", str(err))
            return request.make_response(ack, headers=[("Content-Type", "text/plain; charset=utf-8")], status=400)

    @http.route(
        "/lab/api/v1/<string:endpoint_code>/requests/<string:request_no>/attachments",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def external_request_upload_attachments(self, endpoint_code, request_no, **kwargs):
        endpoint, error = self._lookup_endpoint(endpoint_code)
        if error:
            return error
        if not endpoint.external_allow_request_push:
            return self._json_response({"ok": False, "error": "request_push_disabled"}, status=403)
        domain = [("name", "=", request_no)] + self._request_domain_for_endpoint(endpoint)
        req = request.env["lab.test.request"].sudo().search(domain, limit=1)
        if not req:
            return self._json_response({"ok": False, "error": "request_not_found"}, status=404)

        normalized = []
        content_type = (request.httprequest.content_type or "").lower()
        if content_type.startswith("application/json"):
            try:
                body = json.loads((request.httprequest.data or b"{}").decode("utf-8"))
            except Exception:  # noqa: BLE001
                return self._json_response({"ok": False, "error": "invalid_json"}, status=400)
            payload = body.get("attachments") or []
            normalized, attachment_error = self._normalize_api_attachments(payload)
            if attachment_error:
                return self._json_response(attachment_error, status=400)
        else:
            files = request.httprequest.files.getlist("files")
            for idx, f in enumerate(files, start=1):
                filename = os.path.basename((getattr(f, "filename", "") or "").strip())
                content = f.read() if hasattr(f, "read") else b""
                if not filename or not content:
                    continue
                if len(content) > self._MAX_ATTACHMENT_BYTES:
                    return self._json_response(
                        {
                            "ok": False,
                            "error": "attachment_too_large",
                            "attachment_index": idx,
                            "max_bytes": self._MAX_ATTACHMENT_BYTES,
                        },
                        status=400,
                    )
                normalized.append(
                    {
                        "name": filename,
                        "content": content,
                        "mimetype": (getattr(f, "mimetype", None) or "application/octet-stream"),
                    }
                )
        if not normalized:
            return self._json_response({"ok": False, "error": "attachments_required"}, status=400)
        created = req._create_request_attachments(normalized, source="external_api")
        return self._json_response(
            {
                "ok": True,
                "request_no": req.name,
                "attachments_uploaded": len(created),
                "attachments": [
                    {
                        "id": att.id,
                        "name": att.name,
                        "mimetype": att.mimetype or "",
                        "size": att.file_size or 0,
                    }
                    for att in created
                ],
            }
        )

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
                "patient": {
                    "id": sample.patient_id.id if sample.patient_id else False,
                    "name": sample.patient_id.name if sample.patient_id else "",
                    "identifier": sample.patient_id.identifier if sample.patient_id else "",
                    "passport_no": sample.patient_id.passport_no if sample.patient_id else "",
                },
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
        domain = [
            ("active", "=", True),
            ("profile_only", "=", False),
            ("company_id", "=", endpoint.external_company_id.id),
        ]
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
