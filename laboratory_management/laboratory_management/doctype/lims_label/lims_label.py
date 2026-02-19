from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.utils import log_audit


class LIMSLabel(Document):
	def validate(self):
		self.reference_doctype = (self.reference_doctype or "").strip()
		self.reference_name = (self.reference_name or "").strip()
		if not self.label_template:
			frappe.throw("Label Template is required")
		if not (self.reference_doctype and self.reference_name):
			frappe.throw("Reference DocType and Reference Name are required")
		self.barcode = (self.barcode or "").strip() or self.reference_name

	@frappe.whitelist()
	def action_mark_printed(self):
		self.printed_on = now_datetime()
		self.printed_by = frappe.session.user
		self.status = "Printed"
		self.save(ignore_permissions=True)
		log_audit("print_label", "LIMS Label", self.name, {"ref": f"{self.reference_doctype}:{self.reference_name}"})
		return self.status
