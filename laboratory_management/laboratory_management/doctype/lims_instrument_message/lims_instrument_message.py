from __future__ import annotations

import json
import re

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.utils import log_audit


class LIMSInstrumentMessage(Document):
	def validate(self):
		if not self.process_status:
			self.process_status = "Pending"

	def after_insert(self):
		try:
			self.action_parse()
		except Exception as exc:
			self.process_status = "Failed"
			self.error_message = str(exc)
			self.save(ignore_permissions=True)

	@frappe.whitelist()
	def action_parse(self):
		parsed = _parse_payload(self.message_type, self.raw_payload or "")
		self.parsed_sample_barcode = parsed.get("barcode")
		self.parsed_service_code = parsed.get("service")
		self.parsed_result_value = parsed.get("result")
		self.parsed_payload = json.dumps(parsed, ensure_ascii=True, indent=2)
		self.process_status = "Parsed"
		self.error_message = None
		self.save(ignore_permissions=True)
		log_audit("parse_instrument_message", "LIMS Instrument Message", self.name, parsed)
		return parsed

	@frappe.whitelist()
	def action_import_result(self):
		if self.process_status == "Processed":
			return self.linked_sample
		try:
			if not self.parsed_payload:
				self.action_parse()

			barcode = self.parsed_sample_barcode
			service = self.parsed_service_code
			value = self.parsed_result_value
			if not barcode or not service or value in (None, ""):
				frappe.throw("Parsed payload does not contain barcode/service/result")

			sample_name = frappe.db.get_value("LIMS Sample", {"sample_barcode": barcode}, "name")
			if not sample_name:
				frappe.throw(f"No sample found for barcode {barcode}")
			sample = frappe.get_doc("LIMS Sample", sample_name)
			row = _resolve_sample_item_row(sample, self.instrument, str(service))
			if not row:
				frappe.throw(f"Sample {sample_name} does not contain analysis service for code {service}")

			from laboratory_management.laboratory_management.doctype.lims_worksheet import lims_worksheet

			lims_worksheet.capture_result(sample_name, row.name, str(value), instrument=self.instrument)
			self.linked_sample = sample_name
			self.sample_item_row = row.name
			self.process_status = "Processed"
			self.processed_on = now_datetime()
			self.error_message = None
			self.save(ignore_permissions=True)
			log_audit(
				"import_instrument_result",
				"LIMS Instrument Message",
				self.name,
				{"sample": sample_name, "sample_item_row": row.name, "service": service},
			)
			return sample_name
		except Exception as exc:
			self.process_status = "Failed"
			self.error_message = str(exc)
			self.save(ignore_permissions=True)
			raise


def _resolve_sample_item_row(sample_doc, instrument: str | None, external_code: str):
	code = (external_code or "").strip()
	if not code:
		return None
	code_l = code.lower()

	# 1) Match by analysis_service name (legacy behavior).
	for d in sample_doc.analysis_items or []:
		if (d.analysis_service or "").strip().lower() == code_l:
			return d

	# 2) Match by LIMS Analysis Service.service_code.
	service_names = [d.analysis_service for d in (sample_doc.analysis_items or []) if d.analysis_service]
	if service_names:
		rows = frappe.get_all(
			"LIMS Analysis Service",
			filters={"name": ["in", list(set(service_names))]},
			fields=["name", "service_code"],
		)
		by_code = {(r.service_code or "").strip().lower(): r.name for r in rows if (r.service_code or "").strip()}
		matched = by_code.get(code_l)
		if matched:
			for d in sample_doc.analysis_items or []:
				if d.analysis_service == matched:
					return d

	# 3) Match by instrument-specific mapping table.
	# Use field-based lookup instead of docname lookup so mapping still works even
	# if the mapping record gets renamed by users.
	if instrument:
		mapping_name = frappe.db.get_value(
			"LIMS Instrument Mapping",
			{"instrument": instrument, "is_active": 1},
			"name",
		)
		if mapping_name:
			mapping = frappe.get_doc("LIMS Instrument Mapping", mapping_name)
			for item in mapping.items or []:
				if (item.external_code or "").strip().lower() == code_l and item.analysis_service:
					for d in sample_doc.analysis_items or []:
						if d.analysis_service == item.analysis_service:
							return d
	return None


def _parse_payload(message_type: str, payload: str) -> dict:
	payload = payload or ""
	if message_type == "HL7":
		return _parse_hl7(payload)
	if message_type == "ASTM":
		return _parse_astm(payload)
	if message_type == "JSON":
		try:
			data = json.loads(payload)
			return {
				"barcode": data.get("barcode") or data.get("sample"),
				"service": data.get("service") or data.get("analysis_service"),
				"result": data.get("result") or data.get("value"),
			}
		except Exception:
			return {}
	return {}


def _parse_hl7(payload: str) -> dict:
	barcode = None
	service = None
	result = None
	for line in payload.splitlines():
		parts = line.split("|")
		if not parts:
			continue
		if parts[0] == "OBR":
			barcode = (parts[2] if len(parts) > 2 else None) or (parts[3] if len(parts) > 3 else None)
		if parts[0] == "OBX":
			code_field = parts[3] if len(parts) > 3 else ""
			service = (code_field.split("^")[0] if code_field else None) or service
			result = parts[5] if len(parts) > 5 else result
	return {"barcode": _norm(barcode), "service": _norm(service), "result": _norm(result)}


def _parse_astm(payload: str) -> dict:
	barcode = None
	service = None
	result = None
	for line in payload.splitlines():
		# Common ASTM segments: O for order, R for result
		if line.startswith("O|"):
			parts = line.split("|")
			barcode = parts[2] if len(parts) > 2 else barcode
		if line.startswith("R|"):
			parts = line.split("|")
			if len(parts) > 2:
				m = re.search(r"\^\^\^(?P<svc>[^\^|]+)", parts[2])
				service = (m.group("svc") if m else parts[2]).strip()
			result = parts[3] if len(parts) > 3 else result
	return {"barcode": _norm(barcode), "service": _norm(service), "result": _norm(result)}


def _norm(value):
	if value is None:
		return None
	v = str(value).strip()
	return v or None
