from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSContainerType(Document):
	def validate(self):
		self.container_type_name = (self.container_type_name or "").strip()
		if not self.container_type_name:
			frappe.throw("Container Type Name is required")
		self.code = (self.code or self.container_type_name).strip().upper()
