from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSAnalysisCategory(Document):
	def validate(self):
		self.category_name = (self.category_name or "").strip()
		if not self.category_name:
			frappe.throw("Category Name is required")
		self.code = (self.code or self.category_name).strip().upper()
