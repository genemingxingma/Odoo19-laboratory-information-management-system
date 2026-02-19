from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSAnalysisSpecification(Document):
	def validate(self):
		self.spec_name = (self.spec_name or "").strip()
		if not self.spec_name:
			frappe.throw("Specification Name is required")
		if not self.analysis_service:
			frappe.throw("Analysis Service is required")
		if (self.priority or 0) < 0:
			frappe.throw("Priority cannot be negative")
		if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
			frappe.throw("Effective From cannot be after Effective To")

		# Normalize allowed values (newline-separated).
		if self.allowed_values:
			lines = [v.strip() for v in (self.allowed_values or "").splitlines() if v.strip()]
			self.allowed_values = "\n".join(lines) if lines else None

