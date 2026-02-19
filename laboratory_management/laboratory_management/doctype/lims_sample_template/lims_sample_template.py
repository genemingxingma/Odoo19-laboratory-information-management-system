from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSSampleTemplate(Document):
	def validate(self):
		self.template_name = (self.template_name or "").strip()
		if not self.template_name:
			frappe.throw("Template Name is required")
		if not self.sample_type:
			frappe.throw("Sample Type is required")
		if not (self.analysis_profile or self.items):
			frappe.throw("Analysis Profile or Template Items are required")
