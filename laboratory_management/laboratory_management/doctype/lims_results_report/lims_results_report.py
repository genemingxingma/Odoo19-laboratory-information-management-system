from __future__ import annotations

import json

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.security import ROLE_LIMS_MANAGER, ROLE_LIMS_VERIFIER, ensure_roles
from laboratory_management.utils import log_audit


class LIMSResultsReport(Document):
	def validate(self):
		if not self.status:
			self.status = "Draft"
		if not self.revision:
			self.revision = 1
		if self.previous_report:
			prev = frappe.get_doc("LIMS Results Report", self.previous_report)
			# Guard revision chain integrity: previous report must belong to same sample.
			if self.sample and prev.sample and self.sample != prev.sample:
				frappe.throw("Previous Report must belong to the same Sample")
			self.revision = int(prev.revision or 1) + 1
			if not self.sample:
				self.sample = prev.sample
		if not self.sample:
			frappe.throw("Sample is required")

	def before_insert(self):
		# Default report title from sample.
		if not self.report_title and self.sample:
			self.report_title = f"Results Report - {self.sample}"

	@frappe.whitelist()
	def action_generate(self, print_format: str | None = None):
		ensure_roles(ROLE_LIMS_MANAGER, ROLE_LIMS_VERIFIER)
		if self.status not in {"Draft", "Released"}:
			frappe.throw("Cannot generate for cancelled/superseded reports")

		pf = (print_format or self.print_format or "").strip() or _get_default_print_format()
		self.print_format = pf

		self.generated_file = frappe.attach_print(
			"LIMS Sample",
			self.sample,
			file_name=f"REPORT-{self.sample}-R{int(self.revision or 1)}",
			print_format=pf,
		)
		self.generated_on = now_datetime()
		self.results_snapshot = json.dumps(_build_sample_snapshot(self.sample), ensure_ascii=True, indent=2)
		self.save(ignore_permissions=True)
		log_audit("generate_results_report", "LIMS Results Report", self.name, {"sample": self.sample, "print_format": pf})
		return {"report": self.name, "file_url": self.generated_file}

	@frappe.whitelist()
	def action_release(self):
		ensure_roles(ROLE_LIMS_VERIFIER)
		if self.status == "Released":
			return self.status
		if not self.generated_file:
			self.action_generate()
		self.status = "Released"
		self.released_by = frappe.session.user
		self.released_on = now_datetime()
		self.save(ignore_permissions=True)
		log_audit("release_results_report", "LIMS Results Report", self.name, {"sample": self.sample})
		return self.status

	@frappe.whitelist()
	def action_supersede(self, reason: str | None = None):
		ensure_roles(ROLE_LIMS_MANAGER)
		if self.status == "Superseded":
			return self.status
		self.status = "Superseded"
		if reason:
			self.supersede_reason = reason
		self.save(ignore_permissions=True)
		log_audit("supersede_results_report", "LIMS Results Report", self.name, {"reason": reason})
		return self.status

	@frappe.whitelist()
	def action_sign(self, signature_file: str):
		ensure_roles(ROLE_LIMS_VERIFIER)
		if self.status not in {"Released"}:
			frappe.throw("Report can be signed only after release")
		signature_type = _detect_signature_type(signature_file)
		if not signature_type:
			frappe.throw("Signature file must be an image or PDF")
		self.signature_file = signature_file
		self.signature_type = signature_type
		self.signed_by = frappe.session.user
		self.signed_on = now_datetime()
		self.save(ignore_permissions=True)
		log_audit("sign_results_report", "LIMS Results Report", self.name, {"signature_type": signature_type})
		return {"signature_file": self.signature_file, "signature_type": self.signature_type}


def _get_default_print_format() -> str:
	# Configurable: if missing, fall back to the built-in "LIMS Results Report".
	if frappe.db.exists("DocType", "LIMS Settings") and frappe.db.exists("LIMS Settings", "LIMS Settings"):
		name = frappe.db.get_value("LIMS Settings", "LIMS Settings", "default_results_report_print_format")
		if name:
			return name
	return "LIMS Results Report"


def _detect_signature_type(file_url: str) -> str | None:
	if not file_url:
		return None
	lower = file_url.lower()
	if lower.endswith(".pdf"):
		return "PDF"
	if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
		return "Image"
	return None


def _build_sample_snapshot(sample_name: str) -> dict:
	doc = frappe.get_doc("LIMS Sample", sample_name)
	# Keep snapshot stable and small (but complete enough for audit).
	items = []
	for row in doc.analysis_items or []:
		abnormal_flag = row.get("abnormal_flag") if hasattr(row, "get") else getattr(row, "abnormal_flag", None)
		items.append(
			{
				"analysis_service": row.analysis_service,
				"method": row.method,
				"unit": row.unit,
				"result_value": row.result_value,
				"result_status": row.result_status,
				# Keep a stable key for downstream consumers while mapping to
				# existing data model field.
				"result_flag": abnormal_flag,
				"reference_range": row.reference_range,
				"is_critical": int(row.is_critical or 0),
				"critical_flag": row.critical_flag,
				"is_delta_alert": int(row.is_delta_alert or 0),
				"delta_percent": row.delta_percent,
			}
		)
	return {
		"sample": doc.name,
		"sample_status": doc.sample_status,
		"patient": doc.patient,
		"customer": doc.customer,
		"sample_type": doc.sample_type,
		"sample_barcode": doc.sample_barcode,
		"published_on": doc.published_on,
		"analysis_items": items,
	}
