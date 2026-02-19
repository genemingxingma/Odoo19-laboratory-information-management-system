from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSInstrumentType(Document):
	def validate(self):
		self.instrument_type_name = (self.instrument_type_name or "").strip()
		if not self.instrument_type_name:
			frappe.throw("Instrument Type Name is required")
		self.code = (self.code or self.instrument_type_name).strip().upper()
