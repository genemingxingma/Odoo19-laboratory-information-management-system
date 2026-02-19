from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from laboratory_management.labels import generate_label_batch_pdf, materialize_batch_labels
from laboratory_management.utils import log_audit


class LIMSLabelBatch(Document):
	def validate(self):
		if not self.label_template:
			frappe.throw("Label Template is required")
		if not self.items:
			frappe.throw("At least one item is required")
		for row in self.items:
			row.reference_doctype = (row.reference_doctype or "").strip()
			row.reference_name = (row.reference_name or "").strip()
			row.barcode = (row.barcode or "").strip() or row.reference_name
			row.copies = int(row.copies or 0) or 1
			if not (row.reference_doctype and row.reference_name):
				frappe.throw("Each item must have Reference DocType and Reference Name")

	@frappe.whitelist()
	def action_generate_pdf(self) -> str:
		"""Create labels + generate a printable PDF, attach it, and return file URL."""
		if self.status == "Cancelled":
			frappe.throw("Cancelled batches cannot be generated")
		materialize_batch_labels(self.name)
		file_url = generate_label_batch_pdf(self.name)
		self.reload()
		self.status = "Generated"
		self.save(ignore_permissions=True)
		log_audit("generate_label_batch_pdf", "LIMS Label Batch", self.name, {"pdf_file": self.pdf_file})
		return file_url

	@frappe.whitelist()
	def action_mark_printed(self):
		if self.status == "Cancelled":
			frappe.throw("Cancelled batches cannot be printed")
		for label_name in frappe.get_all(
			"LIMS Label", filters={"label_batch": self.name, "status": "Draft"}, pluck="name"
		):
			label = frappe.get_doc("LIMS Label", label_name)
			label.action_mark_printed()
		self.status = "Printed"
		self.save(ignore_permissions=True)
		log_audit("mark_label_batch_printed", "LIMS Label Batch", self.name, {"printed_on": now_datetime()})
		return self.status

	@frappe.whitelist()
	def action_cancel(self):
		self.status = "Cancelled"
		self.save(ignore_permissions=True)
		# Keep label records for traceability; mark draft ones cancelled.
		frappe.db.set_value(
			"LIMS Label",
			{"label_batch": self.name, "status": "Draft"},
			"status",
			"Cancelled",
			update_modified=False,
		)
		log_audit("cancel_label_batch", "LIMS Label Batch", self.name)
		return self.status

