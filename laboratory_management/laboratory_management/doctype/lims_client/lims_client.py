import frappe
from frappe.model.document import Document


class LIMSClient(Document):
	@frappe.whitelist()
	def action_sync_from_customer(self):
		if not self.customer:
			frappe.throw("ERPNext Customer is required")
		values = frappe.db.get_value(
			"Customer",
			self.customer,
			["customer_name", "email_id", "mobile_no"],
			as_dict=True,
		)
		if values:
			self.client_name = self.client_name or values.customer_name
			self.contact_email = self.contact_email or values.email_id
			self.contact_phone = self.contact_phone or values.mobile_no
		self.save()
		return self.name
