import frappe
from frappe.model.document import Document


class LIMSInterpretationTemplate(Document):
	def validate(self):
		if (self.priority or 0) < 0:
			frappe.throw("Priority cannot be negative")
