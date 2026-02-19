from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSAnalysisProfile(Document):
	def validate(self):
		self.profile_name = (self.profile_name or "").strip()
		if not self.profile_name:
			frappe.throw("Profile Name is required")
		if not self.items:
			frappe.throw("At least one Analysis Service is required")
