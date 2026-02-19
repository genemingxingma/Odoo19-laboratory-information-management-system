from __future__ import annotations

import frappe

from laboratory_management.labels import generate_label_batch_pdf, materialize_batch_labels
from laboratory_management.security import (
	ROLE_LIMS_ANALYST,
	ROLE_LIMS_MANAGER,
	ROLE_LIMS_SAMPLER,
	ROLE_LIMS_VERIFIER,
	ensure_roles,
)
from frappe.utils import now_datetime


def _get_default_sample_label_template() -> str:
	name = frappe.db.get_value(
		"LIMS Label Template",
		{"is_default": 1, "is_active": 1, "label_target": "Sample"},
		"name",
	)
	if name:
		return name
	# Fallback to any active sample template.
	name = frappe.db.get_value("LIMS Label Template", {"is_active": 1, "label_target": "Sample"}, "name")
	if not name:
		frappe.throw("No active Sample label template found")
	return name


@frappe.whitelist()
def generate_sample_labels_pdf(sample: str, label_template: str | None = None, copies: int | None = 1) -> dict:
	"""Convenience API: create a label batch for a single sample and return PDF URL."""
	ensure_roles(ROLE_LIMS_MANAGER, ROLE_LIMS_SAMPLER, ROLE_LIMS_ANALYST)
	sample = (sample or "").strip()
	if not sample:
		frappe.throw("Sample is required")
	if not frappe.db.exists("LIMS Sample", sample):
		frappe.throw("Sample not found")

	label_template = (label_template or "").strip() or _get_default_sample_label_template()
	if not frappe.db.exists("LIMS Label Template", label_template):
		frappe.throw("Label Template not found")
	copies = int(copies or 0) or 1
	if copies < 1 or copies > 100:
		frappe.throw("Copies must be between 1 and 100")

	batch = frappe.new_doc("LIMS Label Batch")
	batch.naming_series = "LIMS-LB-.YYYY.-"
	batch.label_template = label_template
	batch.status = "Draft"
	batch.append(
		"items",
		{
			"reference_doctype": "LIMS Sample",
			"reference_name": sample,
			"barcode": sample,
			"copies": copies,
		},
	)
	batch.insert(ignore_permissions=True)

	materialize_batch_labels(batch.name)
	file_url = generate_label_batch_pdf(batch.name)
	batch.reload()
	batch.status = "Generated"
	batch.save(ignore_permissions=True)
	return {"batch": batch.name, "file_url": file_url}


@frappe.whitelist()
def generate_results_report_pdf(sample: str, print_format: str | None = None, release: int | None = 1) -> dict:
	"""Create a Results Report record for a sample and return the PDF URL.

	This keeps a revisioned trail (each call generates a new revision if a prior
	released report exists).
	"""
	ensure_roles(ROLE_LIMS_MANAGER, ROLE_LIMS_VERIFIER)
	sample = (sample or "").strip()
	if not sample:
		frappe.throw("Sample is required")
	if not frappe.db.exists("LIMS Sample", sample):
		frappe.throw("Sample not found")

	# Find latest released report to revision from.
	prev = frappe.db.get_value(
		"LIMS Results Report",
		{"sample": sample, "status": "Released"},
		"name",
		order_by="revision desc",
	)

	doc = frappe.new_doc("LIMS Results Report")
	doc.naming_series = "LIMS-RPT-.YYYY.-"
	doc.sample = sample
	doc.previous_report = prev
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	res = doc.action_generate(print_format=print_format)
	if int(release or 0):
		doc.action_release()
	return {"report": doc.name, "file_url": res.get("file_url")}


@frappe.whitelist()
def receive_instrument_message(instrument: str, message_type: str, raw_payload: str) -> dict:
	"""Create an Instrument Message from an external integration.

	Caller should authenticate using an API key / secret.
	"""
	ensure_roles(ROLE_LIMS_MANAGER, ROLE_LIMS_ANALYST)
	instrument = (instrument or "").strip()
	message_type = (message_type or "").strip()
	raw_payload = raw_payload or ""
	if not instrument or not frappe.db.exists("LIMS Instrument", instrument):
		frappe.throw("Valid Instrument is required")
	if message_type not in {"HL7", "ASTM", "JSON"}:
		frappe.throw("Message Type must be HL7, ASTM, or JSON")
	if not raw_payload.strip():
		frappe.throw("Raw Payload is required")

	msg = frappe.new_doc("LIMS Instrument Message")
	msg.naming_series = "LIMSGW-.YYYY.-"
	msg.instrument = instrument
	msg.message_type = message_type
	msg.raw_payload = raw_payload
	msg.process_status = "Pending"
	msg.attempts = 0
	msg.last_attempt_on = now_datetime()
	msg.flags.ignore_permissions = True
	msg.insert(ignore_permissions=True)
	return {"message": msg.name, "status": msg.process_status}
