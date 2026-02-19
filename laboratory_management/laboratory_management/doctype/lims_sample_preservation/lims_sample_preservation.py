from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSSamplePreservation(Document):
	def validate(self):
		self.preservation_name = (self.preservation_name or "").strip()
		if not self.preservation_name:
			frappe.throw("Preservation Name is required")
		self.code = (self.code or self.preservation_name).strip().upper()
