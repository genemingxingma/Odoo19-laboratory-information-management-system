from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

from laboratory_management.utils import log_audit


class LIMSEQAPlan(Document):
	def validate(self):
		if (self.acceptance_z_score or 0) <= 0:
			frappe.throw("Acceptance Z Score must be greater than 0")
		if self.due_date and getdate(self.due_date) < getdate(nowdate()):
			if self.status in {"Draft", "Issued"}:
				self.status = "Overdue"

	@frappe.whitelist()
	def action_issue(self):
		if self.status not in {"Draft", "Overdue"}:
			frappe.throw("Only Draft/Overdue plans can be issued")
		self.status = "Issued"
		self.save(ignore_permissions=True)
		log_audit("issue_eqa_plan", "LIMS EQA Plan", self.name, {"due_date": self.due_date})
		return self.status

	@frappe.whitelist()
	def action_close(self):
		rows = frappe.get_all("LIMS EQA Result", filters={"eqa_plan": self.name}, fields=["evaluation"])
		if not rows:
			frappe.throw("Cannot close EQA plan without results")
		self.status = "Closed"
		self.save(ignore_permissions=True)
		log_audit("close_eqa_plan", "LIMS EQA Plan", self.name, {"result_count": len(rows)})
		return self.status
