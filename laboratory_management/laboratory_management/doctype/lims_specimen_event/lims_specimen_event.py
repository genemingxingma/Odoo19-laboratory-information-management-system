from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.utils import log_audit


class LIMSSpecimenEvent(Document):
	def validate(self):
		self.event_on = self.event_on or now_datetime()
		self.performed_by = self.performed_by or frappe.session.user
		sample = frappe.get_doc("LIMS Sample", self.sample)
		settings = frappe.get_cached_doc("LIMS Settings") if frappe.db.exists("DocType", "LIMS Settings") else None
		strict_barcode = int(settings.enable_specimen_barcode_check or 0) if settings else 1
		if not self.barcode:
			self.barcode = sample.sample_barcode or sample.name
		if strict_barcode and sample.sample_barcode and self.barcode != sample.sample_barcode:
			frappe.throw("Barcode does not match sample barcode")

	def after_insert(self):
		_apply_event_to_sample(self)
		log_audit(
			"specimen_event",
			"LIMS Sample",
			self.sample,
			{"event": self.event_type, "barcode": self.barcode, "event_name": self.name},
		)


def _apply_event_to_sample(event_doc):
	sample = frappe.get_doc("LIMS Sample", event_doc.sample)
	if not sample.sample_barcode:
		sample.sample_barcode = event_doc.barcode

	if event_doc.event_type == "Collected":
		sample.specimen_status = "Collected"
		sample.collected_on = event_doc.event_on
		sample.collection_datetime = sample.collection_datetime or event_doc.event_on
	elif event_doc.event_type == "In Transit":
		sample.specimen_status = "In Transit"
		sample.in_transit_on = event_doc.event_on
	elif event_doc.event_type == "Received":
		sample.specimen_status = "Accessioned"
		sample.accessioned_on = event_doc.event_on
		sample.received_datetime = sample.received_datetime or event_doc.event_on
		if sample.sample_status in {"Draft", "Sampled"}:
			sample.sample_status = "Received"
	elif event_doc.event_type == "Rejected":
		sample.specimen_status = "Rejected"
	elif event_doc.event_type == "Disposed":
		sample.specimen_status = "Disposed"

	sample.save(ignore_permissions=True)
