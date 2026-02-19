from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.utils import log_audit


class LIMSCAPA(Document):
	def validate(self):
		self.issue_title = (self.issue_title or "").strip()
		if not self.issue_title:
			frappe.throw("Issue Title is required")

	def on_update(self):
		log_audit(
			"update_capa",
			"LIMS CAPA",
			self.name,
			{"status": self.status, "source_type": self.source_type, "source_name": self.source_name},
		)

	@frappe.whitelist()
	def action_close(self, comment: str | None = None):
		if self.status == "Closed":
			return self.status
		self.status = "Closed"
		self.closed_by = frappe.session.user
		self.closed_on = now_datetime()
		if comment:
			self.closure_comment = comment
		self.save(ignore_permissions=True)
		log_audit("close_capa", "LIMS CAPA", self.name, {"comment": comment})
		return self.status

