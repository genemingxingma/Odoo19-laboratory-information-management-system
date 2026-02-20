import json
from datetime import datetime

from odoo import _, models
from odoo.exceptions import ValidationError


class LabProtocolAdapter(models.AbstractModel):
    _name = "lab.protocol.adapter"
    _description = "Laboratory Protocol Adapter"

    @staticmethod
    def _hl7_split(raw_message):
        lines = [ln.strip() for ln in (raw_message or "").replace("\r\n", "\r").replace("\n", "\r").split("\r") if ln.strip()]
        segments = []
        for line in lines:
            fields = line.split("|")
            segments.append((fields[0], fields))
        return segments

    @staticmethod
    def _hl7_component(value, idx=0):
        if not value:
            return ""
        parts = value.split("^")
        return parts[idx] if idx < len(parts) else ""

    def _hl7_get_expr(self, by_name, expr):
        """Expr format: SEG[occ].field.component.subcomponent
        Examples:
        PID.5.2 -> given name
        OBR[2].3 -> second OBR accession
        OBX.5 -> OBX value
        """
        if not expr or "." not in expr:
            return ""
        left, *rest = expr.split(".")
        occ = 1
        seg = left
        if "[" in left and left.endswith("]"):
            seg = left.split("[", 1)[0]
            try:
                occ = int(left.split("[", 1)[1][:-1])
            except Exception:  # noqa: BLE001
                occ = 1
        segments = by_name.get(seg, [])
        if len(segments) < occ:
            return ""
        fields = segments[occ - 1]
        try:
            field_idx = int(rest[0])
        except Exception:  # noqa: BLE001
            return ""
        if field_idx >= len(fields):
            return ""
        value = fields[field_idx]
        if len(rest) >= 2:
            try:
                comp_idx = int(rest[1]) - 1
                comps = value.split("^")
                value = comps[comp_idx] if comp_idx < len(comps) else ""
            except Exception:  # noqa: BLE001
                value = ""
        if len(rest) >= 3:
            try:
                sub_idx = int(rest[2]) - 1
                subs = value.split("&")
                value = subs[sub_idx] if sub_idx < len(subs) else ""
            except Exception:  # noqa: BLE001
                value = ""
        return value or ""

    def parse_hl7_message(self, raw_message, field_map=False):
        segments = self._hl7_split(raw_message)
        if not segments or segments[0][0] != "MSH":
            raise ValidationError(_("Invalid HL7 message: missing MSH segment."))

        by_name = {}
        for name, fields in segments:
            by_name.setdefault(name, []).append(fields)

        msh = by_name.get("MSH", [[]])[0]
        msg_type_raw = msh[8] if len(msh) > 8 else ""
        control_id = msh[9] if len(msh) > 9 else ""
        msg_type = self._hl7_component(msg_type_raw, 0)
        trigger = self._hl7_component(msg_type_raw, 1)
        mapped_type = "order" if msg_type == "ORM" else "result"
        if msg_type == "ORU":
            mapped_type = "result"

        pid = by_name.get("PID", [[]])[0]
        patient_name = ""
        if len(pid) > 5:
            family = self._hl7_component(pid[5], 0)
            given = self._hl7_component(pid[5], 1)
            patient_name = ("%s %s" % (given, family)).strip() or family or given

        obr_list = by_name.get("OBR", [])
        obx_list = by_name.get("OBX", [])
        accession = ""
        lines = []
        results = []

        for obr in obr_list:
            accession = accession or (obr[3] if len(obr) > 3 else "")
            svc = self._hl7_component(obr[4], 0) if len(obr) > 4 else ""
            if svc:
                lines.append({"service_code": svc, "qty": 1})

        for obx in obx_list:
            svc = self._hl7_component(obx[3], 0) if len(obx) > 3 else ""
            val = obx[5] if len(obx) > 5 else ""
            note = obx[8] if len(obx) > 8 else ""
            if svc:
                results.append({"service_code": svc, "result": val, "note": note})

        if mapped_type == "order":
            payload = {
                "patient_name": patient_name or _("External Patient"),
                "priority": "routine",
                "sample_type": "blood",
                "lines": lines,
            }
        else:
            payload = {
                "accession": accession,
                "results": results,
            }
        # Optional fine-grained field mapping, e.g. {"patient_name": "PID.5.2", "accession": "OBR.3"}
        if isinstance(field_map, dict):
            for key, expr in field_map.items():
                extracted = self._hl7_get_expr(by_name, expr)
                if extracted:
                    payload[key] = extracted
        return {
            "message_type": mapped_type,
            "payload": payload,
            "external_uid": control_id or False,
            "meta": {"hl7_type": msg_type, "hl7_trigger": trigger, "control_id": control_id},
        }

    def build_hl7_ack(self, ack_code, control_id, text=""):
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        msh = "MSH|^~\\&|ODOO|LAB|EXT|REMOTE|%s||ACK|%s|P|2.5" % (ts, control_id or "CTRL")
        msa = "MSA|%s|%s|%s" % (ack_code or "AA", control_id or "CTRL", text or "")
        return "\r".join([msh, msa]) + "\r"

    def build_hl7_message(self, payload, message_type, endpoint_code="", job_name=""):
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        if message_type == "order":
            msh = "MSH|^~\\&|LAB|ODOO|%s|EXT|%s||ORM^O01|%s|P|2.5" % (endpoint_code or "ENDP", ts, job_name or "JOB")
            pid = "PID|||%s||%s" % (payload.get("request") or "", payload.get("patient_name") or "Unknown^Patient")
            lines = payload.get("lines") or []
            segments = [msh, pid]
            for idx, line in enumerate(lines, start=1):
                code = line.get("service_code") or "UNKNOWN"
                segments.append("ORC|NW|%s-%s" % (job_name or "JOB", idx))
                segments.append("OBR|%s|%s|%s|%s^%s" % (idx, payload.get("request_no") or "", payload.get("request_no") or "", code, code))
            return "\r".join(segments) + "\r"

        msh = "MSH|^~\\&|LAB|ODOO|%s|EXT|%s||ORU^R01|%s|P|2.5" % (endpoint_code or "ENDP", ts, job_name or "JOB")
        pid = "PID|||%s||%s" % (payload.get("sample") or "", payload.get("patient_name") or "Unknown^Patient")
        obr = "OBR|1|%s|%s|LAB^RESULT" % (payload.get("accession") or "", payload.get("accession") or "")
        segments = [msh, pid, obr]
        for idx, row in enumerate(payload.get("results") or [], start=1):
            code = row.get("service_code") or "TEST"
            val = row.get("result") or ""
            flag = row.get("flag") or ""
            segments.append("OBX|%s|ST|%s^%s||%s|||%s" % (idx, code, code, val, flag))
        return "\r".join(segments) + "\r"

    def validate_fhir_profile(self, data):
        if not isinstance(data, dict):
            raise ValidationError(_("FHIR payload must be JSON object."))
        resource_type = data.get("resourceType")
        if not resource_type:
            raise ValidationError(_("FHIR payload missing resourceType."))
        if resource_type == "ServiceRequest":
            if not (data.get("code") and (data.get("code") or {}).get("coding")):
                raise ValidationError(_("FHIR ServiceRequest missing code.coding."))
        if resource_type == "Observation":
            if not ((data.get("code") or {}).get("coding")):
                raise ValidationError(_("FHIR Observation missing code.coding."))
            if (
                data.get("valueString") in (None, "")
                and (data.get("valueQuantity") or {}).get("value") in (None, "")
            ):
                raise ValidationError(_("FHIR Observation missing valueString or valueQuantity.value."))
        if resource_type == "DiagnosticReport":
            if not data.get("result"):
                raise ValidationError(_("FHIR DiagnosticReport missing result entries."))
        return True

    def parse_fhir_resource(self, data):
        self.validate_fhir_profile(data)
        if not isinstance(data, dict):
            raise ValidationError(_("FHIR payload must be JSON object."))
        resource_type = data.get("resourceType")
        if resource_type == "ServiceRequest":
            code = (((data.get("code") or {}).get("coding") or [{}])[0]).get("code")
            patient_name = (((data.get("subject") or {}).get("display") or "").strip()) or _("External Patient")
            return {
                "message_type": "order",
                "payload": {
                    "patient_name": patient_name,
                    "priority": "routine",
                    "sample_type": "blood",
                    "lines": [{"service_code": code, "qty": 1}] if code else [],
                },
                "external_uid": data.get("id") or False,
                "meta": {"resourceType": resource_type},
            }
        if resource_type in ("DiagnosticReport", "Observation"):
            accession = (((data.get("identifier") or [{}])[0]).get("value")) or data.get("id")
            results = []
            if resource_type == "Observation":
                code = (((data.get("code") or {}).get("coding") or [{}])[0]).get("code")
                value = data.get("valueString") or data.get("valueQuantity", {}).get("value")
                results.append({"service_code": code, "result": str(value or ""), "note": ""})
            else:
                for item in data.get("result", []):
                    code = (((item.get("code") or {}).get("coding") or [{}])[0]).get("code")
                    value = item.get("valueString") or item.get("valueQuantity", {}).get("value")
                    results.append({"service_code": code, "result": str(value or ""), "note": ""})
            return {
                "message_type": "result",
                "payload": {"accession": accession, "results": results},
                "external_uid": data.get("id") or False,
                "meta": {"resourceType": resource_type},
            }
        raise ValidationError(_("Unsupported FHIR resourceType: %s") % (resource_type or ""))

    def build_fhir_outcome(self, ok=True, detail="accepted"):
        return {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "information" if ok else "error",
                    "code": "informational" if ok else "exception",
                    "details": {"text": detail},
                }
            ],
        }

    def build_fhir_resource(self, payload, message_type):
        if message_type == "order":
            code = (((payload.get("lines") or [{}])[0]).get("service_code")) or "LAB"
            return {
                "resourceType": "ServiceRequest",
                "id": payload.get("job") or payload.get("request_no") or "REQ",
                "status": "active",
                "intent": "order",
                "priority": (payload.get("priority") or "routine").lower(),
                "code": {"coding": [{"system": "urn:imytest:lab:service", "code": code}]},
                "subject": {"display": payload.get("patient_name") or "Unknown Patient"},
            }
        observations = []
        for idx, row in enumerate(payload.get("results") or [], start=1):
            observations.append(
                {
                    "resourceType": "Observation",
                    "id": "%s-%s" % (payload.get("accession") or "ACC", idx),
                    "status": "final",
                    "code": {"coding": [{"system": "urn:imytest:lab:service", "code": row.get("service_code") or "LAB"}]},
                    "valueString": str(row.get("result") or ""),
                }
            )
        return {
            "resourceType": "DiagnosticReport",
            "id": payload.get("accession") or payload.get("job") or "REPORT",
            "status": "final",
            "result": observations,
        }

    def to_json_text(self, data):
        return json.dumps(data, ensure_ascii=False, indent=2)
