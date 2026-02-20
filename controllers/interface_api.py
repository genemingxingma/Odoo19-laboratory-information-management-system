import base64
import json

from odoo import http
from odoo.http import request


class LaboratoryInterfaceApi(http.Controller):
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
                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
            except Exception:  # noqa: BLE001
                return False
            if ":" not in decoded:
                return False
            username, password = decoded.split(":", 1)
            return bool(username == (endpoint.username or "") and password == (endpoint.password or ""))
        return False

    @http.route(
        "/lab/interface/inbound/<string:endpoint_code>",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def interface_inbound(self, endpoint_code, **kwargs):
        endpoint = request.env["lab.interface.endpoint"].sudo().search(
            [("code", "=", endpoint_code), ("active", "=", True)],
            limit=1,
        )
        if not endpoint:
            return {"ok": False, "ack_code": "AR", "error": "endpoint_not_found"}
        if endpoint.direction not in ("inbound", "bidirectional"):
            return {"ok": False, "ack_code": "AR", "error": "direction_not_allowed"}
        if not self._authorize_endpoint(endpoint):
            return {"ok": False, "ack_code": "AR", "error": "unauthorized"}

        body = request.jsonrequest or {}
        message_type = body.get("message_type") or "order"
        payload = body.get("payload") or {}
        external_uid = body.get("external_uid")
        raw_message = body.get("raw_message")
        source_ip = request.httprequest.remote_addr or ""

        try:
            job = endpoint.ingest_message(
                message_type=message_type,
                payload=payload,
                external_uid=external_uid,
                source_ip=source_ip,
                raw_message=raw_message,
            )
            request.env["lab.interface.audit.log"].sudo().log_event(
                action="ack",
                direction="inbound",
                endpoint=endpoint,
                job=job,
                external_uid=external_uid,
                source_ip=source_ip,
                payload=payload,
                result={"ack_code": job.ack_code or "AA"},
                state=job.state,
            )
            return {
                "ok": job.state == "done",
                "ack_code": job.ack_code or ("AA" if job.state == "done" else "AE"),
                "job_id": job.id,
                "job_name": job.name,
                "state": job.state,
                "error": job.error_message or "",
            }
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "ack_code": "AR", "error": str(err)}

    @http.route(
        "/lab/interface/inbound/<string:endpoint_code>/raw",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def interface_inbound_raw(self, endpoint_code, **kwargs):
        endpoint = request.env["lab.interface.endpoint"].sudo().search(
            [("code", "=", endpoint_code), ("active", "=", True)],
            limit=1,
        )
        if not endpoint:
            return request.make_response("endpoint_not_found", status=404)
        if endpoint.direction not in ("inbound", "bidirectional"):
            return request.make_response("direction_not_allowed", status=403)
        if not self._authorize_endpoint(endpoint):
            return request.make_response("unauthorized", status=401)

        raw = request.httprequest.get_data(as_text=True) or ""
        source_ip = request.httprequest.remote_addr or ""
        adapter = request.env["lab.protocol.adapter"].sudo()
        schema = {}
        try:
            schema = json.loads(endpoint.mapping_schema or "{}")
        except Exception:  # noqa: BLE001
            schema = {}

        try:
            protocol = endpoint.protocol
            parsed = {}
            if protocol == "hl7v2":
                parsed = adapter.parse_hl7_message(raw, field_map=(schema.get("hl7_field_map") or {}))
            elif protocol == "fhir":
                parsed = adapter.parse_fhir_resource(json.loads(raw or "{}"))
            else:
                parsed = {
                    "message_type": "order",
                    "payload": json.loads(raw or "{}"),
                    "external_uid": False,
                    "meta": {},
                }

            job = endpoint.ingest_message(
                message_type=parsed.get("message_type") or "order",
                payload=parsed.get("payload") or {},
                external_uid=parsed.get("external_uid"),
                source_ip=source_ip,
                raw_message=raw,
            )
            if protocol == "hl7v2":
                control_id = (parsed.get("meta") or {}).get("control_id")
                ack = adapter.build_hl7_ack(job.ack_code or "AA", control_id, job.error_message or "")
                request.env["lab.interface.audit.log"].sudo().log_event(
                    action="ack",
                    direction="inbound",
                    endpoint=endpoint,
                    job=job,
                    external_uid=parsed.get("external_uid"),
                    source_ip=source_ip,
                    payload=raw,
                    result={"ack": ack},
                    state=job.state,
                )
                return request.make_response(ack, headers=[("Content-Type", "text/plain; charset=utf-8")], status=200)

            body = adapter.build_fhir_outcome(ok=job.state == "done", detail=job.error_message or "accepted")
            request.env["lab.interface.audit.log"].sudo().log_event(
                action="ack",
                direction="inbound",
                endpoint=endpoint,
                job=job,
                external_uid=parsed.get("external_uid"),
                source_ip=source_ip,
                payload=raw,
                result=body,
                state=job.state,
            )
            return request.make_response(
                json.dumps(body),
                headers=[("Content-Type", "application/fhir+json; charset=utf-8")],
                status=200,
            )
        except Exception as err:  # noqa: BLE001
            if endpoint.protocol == "hl7v2":
                ack = adapter.build_hl7_ack("AR", "", str(err))
                return request.make_response(ack, headers=[("Content-Type", "text/plain; charset=utf-8")], status=400)
            body = adapter.build_fhir_outcome(ok=False, detail=str(err))
            return request.make_response(
                json.dumps(body),
                headers=[("Content-Type", "application/fhir+json; charset=utf-8")],
                status=400,
            )

    @http.route(
        "/lab/interface/outbound/<string:endpoint_code>/ack",
        type="jsonrpc",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def interface_outbound_ack(self, endpoint_code, **kwargs):
        endpoint = request.env["lab.interface.endpoint"].sudo().search(
            [("code", "=", endpoint_code), ("active", "=", True)],
            limit=1,
        )
        if not endpoint:
            return {"ok": False, "error": "endpoint_not_found"}
        if endpoint.direction not in ("outbound", "bidirectional"):
            return {"ok": False, "error": "direction_not_allowed"}
        if not self._authorize_endpoint(endpoint):
            return {"ok": False, "error": "unauthorized"}

        body = request.jsonrequest or {}
        source_ip = request.httprequest.remote_addr or ""
        try:
            endpoint.register_outbound_ack(
                ack_code=(body.get("ack_code") or "").upper(),
                job_name=body.get("job_name"),
                job_id=body.get("job_id"),
                external_uid=body.get("external_uid"),
                ack_message=body.get("message") or "",
                source_ip=source_ip,
                payload=body.get("payload") or {},
            )
            return {"ok": True}
        except Exception as err:  # noqa: BLE001
            return {"ok": False, "error": str(err)}
