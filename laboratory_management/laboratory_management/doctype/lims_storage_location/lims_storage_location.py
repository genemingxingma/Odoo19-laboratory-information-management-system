from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSStorageLocation(Document):
	def validate(self):
		self.location_name = (self.location_name or "").strip()
		if not self.location_name:
			frappe.throw("Location Name is required")
