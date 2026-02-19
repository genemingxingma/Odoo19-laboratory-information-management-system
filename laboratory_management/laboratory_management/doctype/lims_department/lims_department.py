from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSDepartment(Document):
	def validate(self):
		self.department_name = (self.department_name or "").strip()
		if not self.department_name:
			frappe.throw("Department Name is required")
		self.code = (self.code or self.department_name).strip().upper()
