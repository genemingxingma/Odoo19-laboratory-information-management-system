from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime


def log_audit(action: str, reference_doctype: str | None = None, reference_name: str | None = None, details: dict | str | None = None):
	if not frappe.db.exists("DocType", "LIMS Audit Log"):
		return
	payload = details
	if isinstance(details, dict):
		payload = json.dumps(details, ensure_ascii=True, default=str)
	frappe.get_doc(
		{
			"doctype": "LIMS Audit Log",
			"audit_datetime": now_datetime(),
			"action": action,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"performed_by": frappe.session.user,
			"details": payload,
		}
	).insert(ignore_permissions=True)
