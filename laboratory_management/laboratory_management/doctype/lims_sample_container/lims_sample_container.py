from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSSampleContainer(Document):
	def validate(self):
		self.container_label = (self.container_label or "").strip() or None
		self.barcode = (self.barcode or "").strip() or None
		if not self.container_type:
			frappe.throw("Container Type is required")
		if not (self.container_label or self.barcode):
			self.container_label = self.name
