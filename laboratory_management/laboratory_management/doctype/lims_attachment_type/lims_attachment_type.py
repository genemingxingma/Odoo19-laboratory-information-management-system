from __future__ import annotations

import frappe
from frappe.model.document import Document


class LIMSAttachmentType(Document):
	def validate(self):
		self.attachment_type_name = (self.attachment_type_name or "").strip()
		if not self.attachment_type_name:
			frappe.throw("Attachment Type Name is required")
