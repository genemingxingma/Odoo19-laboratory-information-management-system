from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSSampleCondition(Document):
	def validate(self):
		self.condition_name = (self.condition_name or "").strip()
		if not self.condition_name:
			frappe.throw("Condition Name is required")
		self.code = (self.code or self.condition_name).strip().upper()
