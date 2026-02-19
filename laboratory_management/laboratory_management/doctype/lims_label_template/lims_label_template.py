from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSLabelTemplate(Document):
	def validate(self):
		self.template_name = (self.template_name or "").strip()
		if not self.template_name:
			frappe.throw("Template Name is required")
		self.label_target = (self.label_target or "Sample").strip() or "Sample"
