from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSSampleMatrix(Document):
	def validate(self):
		self.matrix_name = (self.matrix_name or "").strip()
		if not self.matrix_name:
			frappe.throw("Matrix Name is required")
		self.code = (self.code or self.matrix_name).strip().upper()
