from __future__ import annotations

import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from laboratory_management.security import ROLE_LIMS_ANALYST
from laboratory_management.security import ROLE_LIMS_MANAGER
from laboratory_management.security import ROLE_LIMS_SAMPLER
from laboratory_management.security import ROLE_LIMS_VERIFIER

COA_TEMPLATE = """
<div style=\"font-family:Arial,sans-serif;font-size:12px;\">
	<h2>Certificate of Analysis (COA)</h2>
	<p><b>Sample:</b> {{ doc.name }} | <b>Status:</b> {{ doc.sample_status }}</p>
	<p><b>Customer:</b> {{ doc.customer or '-' }} | <b>Sample Type:</b> {{ doc.sample_type }}</p>
	<table style=\"width:100%;border-collapse:collapse;\" border=\"1\" cellspacing=\"0\" cellpadding=\"4\">
	<tr><th>Service</th><th>Method</th><th>Unit</th><th>Result</th><th>Status</th><th>Verified By</th></tr>
	{% for row in doc.analysis_items %}
	<tr><td>{{ row.analysis_service }}</td><td>{{ row.method or '-' }}</td><td>{{ row.unit or '-' }}</td><td>{{ row.result_value or '-' }}</td><td>{{ row.result_status or '-' }}</td><td>{{ row.verified_by or '-' }}</td></tr>
	{% endfor %}
	</table>
	<p><b>Published On:</b> {{ doc.published_on or '-' }}</p>
	{% if doc.coa_signature_file %}
	<hr>
	<p><b>COA Signature:</b></p>
	{% if doc.coa_signature_type == "Image" %}
		<p><img src=\"{{ doc.coa_signature_file }}\" style=\"max-height:120px;max-width:320px;\"></p>
	{% elif doc.coa_signature_type == "PDF" %}
		<p>Signed PDF: <a href=\"{{ doc.coa_signature_file }}\">{{ doc.coa_signature_file }}</a></p>
	{% endif %}
	<p><b>Signed By:</b> {{ doc.coa_signed_by or '-' }} | <b>Signed On:</b> {{ doc.coa_signed_on or '-' }}</p>
	{% endif %}
</div>
"""

RESULTS_REPORT_TEMPLATE = """
<div style=\"font-family:Arial,sans-serif;font-size:12px;\">
	<h2>Results Report</h2>
	<p><b>Sample:</b> {{ doc.name }} | <b>Status:</b> {{ doc.sample_status }}</p>
	<p><b>Patient:</b> {{ doc.patient or '-' }} | <b>Customer:</b> {{ doc.customer or '-' }}</p>
	<p><b>Sample Type:</b> {{ doc.sample_type }} | <b>Barcode:</b> {{ doc.sample_barcode or '-' }}</p>

	<table style=\"width:100%;border-collapse:collapse;\" border=\"1\" cellspacing=\"0\" cellpadding=\"4\">
	<tr>
		<th>Test</th><th>Result</th><th>Unit</th><th>Flag</th><th>Reference</th><th>Status</th>
	</tr>
	{% for row in doc.analysis_items %}
	<tr>
		<td>{{ row.analysis_service }}</td>
		<td>{{ row.result_value or '-' }}</td>
		<td>{{ row.unit or '-' }}</td>
		<td>{{ row.abnormal_flag or row.critical_flag or '-' }}</td>
		<td>{{ row.reference_range or '-' }}</td>
		<td>{{ row.result_status or '-' }}</td>
	</tr>
	{% endfor %}
	</table>

	{% if doc.final_conclusion %}
	<hr>
	<p><b>Conclusion:</b></p>
	<div style=\"white-space:pre-wrap;\">{{ doc.final_conclusion }}</div>
	{% endif %}

	<p><b>Published On:</b> {{ doc.published_on or '-' }}</p>

	{% if doc.coa_signature_file %}
	<hr>
	<p><b>Signature:</b></p>
	{% if doc.coa_signature_type == "Image" %}
		<p><img src=\"{{ doc.coa_signature_file }}\" style=\"max-height:120px;max-width:320px;\"></p>
	{% elif doc.coa_signature_type == "PDF" %}
		<p>Signed PDF: <a href=\"{{ doc.coa_signature_file }}\">{{ doc.coa_signature_file }}</a></p>
	{% endif %}
	<p><b>Signed By:</b> {{ doc.coa_signed_by or '-' }} | <b>Signed On:</b> {{ doc.coa_signed_on or '-' }}</p>
	{% endif %}
</div>
"""


def after_migrate():
	ensure_lims_roles()
	ensure_lims_coa_print_format()
	ensure_lims_results_report_print_format()
	ensure_lims_settings()
	ensure_rejection_reasons()
	ensure_asset_calibration_fields()
	ensure_lims_workspace()


def ensure_lims_roles():
	for role_name in [ROLE_LIMS_MANAGER, ROLE_LIMS_SAMPLER, ROLE_LIMS_ANALYST, ROLE_LIMS_VERIFIER]:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_lims_coa_print_format():
	name = "LIMS COA"
	data = {
		"doctype": "Print Format",
		"name": name,
		"doc_type": "LIMS Sample",
		"module": "Laboratory Management",
		"print_format_for": "DocType",
		"standard": "No",
		"disabled": 0,
		"print_format_type": "Jinja",
		"custom_format": 1,
		"html": COA_TEMPLATE,
	}
	if frappe.db.exists("Print Format", name):
		doc = frappe.get_doc("Print Format", name)
		for key, value in data.items():
			if key in {"doctype", "name"}:
				continue
			doc.set(key, value)
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc(data).insert(ignore_permissions=True)


def ensure_lims_results_report_print_format():
	name = "LIMS Results Report"
	data = {
		"doctype": "Print Format",
		"name": name,
		"doc_type": "LIMS Sample",
		"module": "Laboratory Management",
		"print_format_for": "DocType",
		"standard": "No",
		"disabled": 0,
		"print_format_type": "Jinja",
		"custom_format": 1,
		"html": RESULTS_REPORT_TEMPLATE,
	}
	if frappe.db.exists("Print Format", name):
		doc = frappe.get_doc("Print Format", name)
		for key, value in data.items():
			if key in {"doctype", "name"}:
				continue
			doc.set(key, value)
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc(data).insert(ignore_permissions=True)


def ensure_lims_settings():
	if not frappe.db.exists("DocType", "LIMS Settings"):
		return
	defaults = {
		"required_verifications": 1,
		"allow_self_verification": 0,
		"auto_receive_samples": 0,
		"auto_verify_samples": 0,
		"auto_create_sales_invoice_on_publish": 0,
		"auto_submit_sales_invoice": 1,
		"auto_create_payment_entry_on_invoice": 0,
		"enforce_specimen_accession_before_result": 1,
		"enable_specimen_barcode_check": 1,
		"eqa_alert_days": 14,
		"instrument_message_auto_process": 1,
		"instrument_message_batch_size": 50,
		"instrument_message_retry_max_attempts": 5,
		"instrument_message_retry_base_minutes": 10,
		"instrument_message_retry_max_minutes": 1440,
		"auto_create_capa_on_eqa_fail": 1,
		"default_results_report_print_format": "LIMS Results Report",
		"specifications_enabled": 1,
		"rejection_workflow_enabled": 1,
		"calibration_alert_days": 7,
		"tat_alert_days": 2,
		"alert_owner": "Administrator",
	}
	if not frappe.db.exists("LIMS Settings", "LIMS Settings"):
		frappe.get_doc({"doctype": "LIMS Settings", **defaults}).save(ignore_permissions=True)
		return
	doc = frappe.get_doc("LIMS Settings", "LIMS Settings")
	changed = False
	for key, value in defaults.items():
		if doc.get(key) in (None, ""):
			doc.set(key, value)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def ensure_rejection_reasons():
	for reason in ["Insufficient Sample", "Contaminated", "Broken Container", "Out Of Stability"]:
		if frappe.db.exists("LIMS Rejection Reason", reason):
			continue
		frappe.get_doc({"doctype": "LIMS Rejection Reason", "reason_title": reason, "is_active": 1}).insert(
			ignore_permissions=True
		)


def ensure_lims_workspace():
	name = "Laboratory Management"
	if not frappe.db.exists("DocType", "Workspace"):
		return

	# Force-sync workspace from the app's workspace export so menu labels stay stable
	# across installs and migrations (and so we can adjust displayed labels without
	# renaming underlying DocTypes).
	path = frappe.get_app_path(
		"laboratory_management",
		"laboratory_management",
		"workspace",
		"laboratory_management",
		"laboratory_management.json",
	)
	try:
		data = json.load(open(path))
	except Exception:
		data = {}

	if not frappe.db.exists("Workspace", name):
		if data:
			doc = frappe.get_doc(data)
			doc.flags.ignore_permissions = True
			doc.insert(ignore_if_duplicate=True)
		return

	doc = frappe.get_doc("Workspace", name)
	changed = False
	if doc.icon != "science":
		doc.icon = "science"
		changed = True
	# Ensure a stable workspace route so app launcher + desktop icon can target it.
	if doc.meta.has_field("route"):
		# Compute from workspace name to avoid hard-coding a route string.
		route = frappe.scrub(name).replace("_", "-")
		if (doc.get("route") or "") != route:
			doc.set("route", route)
			changed = True
	if not doc.public:
		doc.public = 1
		changed = True
	if doc.label != "Laboratory Management":
		doc.label = "Laboratory Management"
		changed = True
	if data:
		# Keep displayed sidebar menu labels in sync with exported workspace.
		if doc.content != data.get("content"):
			doc.content = data.get("content")
			changed = True
		if data.get("links") is not None:
			# Must set child table via doc.set/append, not by raw assignment.
			doc.set("links", [])
			for link in data.get("links") or []:
				doc.append("links", link)
			changed = True
	if changed:
		doc.save(ignore_permissions=True)


def ensure_asset_calibration_fields():
	custom_fields = {
		"Asset": [
			{
				"fieldname": "custom_lims_calibration_section",
				"fieldtype": "Section Break",
				"label": "LIMS Calibration",
				"insert_after": "maintenance_required",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_lims_last_calibration_date",
				"fieldtype": "Date",
				"label": "Last Calibration Date",
				"insert_after": "custom_lims_calibration_section",
			},
			{
				"fieldname": "custom_lims_calibration_cycle_days",
				"fieldtype": "Int",
				"label": "Calibration Cycle (Days)",
				"default": "0",
				"insert_after": "custom_lims_last_calibration_date",
			},
			{
				"fieldname": "custom_lims_calibration_due_date",
				"fieldtype": "Date",
				"label": "Calibration Due Date",
				"insert_after": "custom_lims_calibration_cycle_days",
			},
		]
	}
	create_custom_fields(custom_fields, ignore_validate=True, update=True)
