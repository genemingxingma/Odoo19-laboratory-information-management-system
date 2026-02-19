from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSWorksheetTemplate(Document):
	def validate(self):
		self.template_name = (self.template_name or "").strip()
		if not self.template_name:
			frappe.throw("Template Name is required")
		if not self.items:
			frappe.throw("At least one Analysis Service is required")
