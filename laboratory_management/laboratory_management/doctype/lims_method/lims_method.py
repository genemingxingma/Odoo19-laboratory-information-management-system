import frappe
from frappe.model.document import Document


class LIMSMethod(Document):
	def validate(self):
		self.code = (self.code or "").strip().upper()
		if not self.code:
			frappe.throw("Code is required")
