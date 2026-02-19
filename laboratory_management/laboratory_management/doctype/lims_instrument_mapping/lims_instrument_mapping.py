from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSInstrumentMapping(Document):
	def validate(self):
		if not self.instrument:
			frappe.throw("Instrument is required")
		seen = set()
		for row in self.items or []:
			code = (row.external_code or "").strip()
			row.external_code = code
			if not code:
				frappe.throw("External Code is required in mapping items")
			key = code.lower()
			if key in seen:
				frappe.throw(f"Duplicate External Code in mapping: {code}")
			seen.add(key)

