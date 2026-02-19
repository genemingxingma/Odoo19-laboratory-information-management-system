from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class LIMSCriticalNotification(Document):
	def validate(self):
		if not self.notified_on:
			self.notified_on = now_datetime()
		if self.readback_confirmed_by and not self.readback_confirmed_on:
			self.readback_confirmed_on = now_datetime()
		if self.readback_confirmed_on and not self.readback_confirmed_by:
			frappe.throw("Readback Confirmed By is required when Readback Confirmed On is set")
		if self.readback_confirmed_on:
			self.status = "Completed"


@frappe.whitelist()
def complete_notification(name: str, confirmed_by: str, remarks: str | None = None):
	doc = frappe.get_doc("LIMS Critical Notification", name)
	doc.readback_confirmed_by = confirmed_by
	doc.readback_confirmed_on = now_datetime()
	doc.status = "Completed"
	if remarks:
		doc.remarks = remarks
	doc.save(ignore_permissions=True)
	return {"status": doc.status, "readback_confirmed_on": doc.readback_confirmed_on}
