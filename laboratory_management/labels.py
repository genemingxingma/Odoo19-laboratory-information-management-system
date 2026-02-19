from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import now_datetime

from laboratory_management.utils import log_audit


def materialize_batch_labels(batch_name: str) -> int:
	"""Create Draft LIMS Label rows for the batch items (idempotent)."""
	batch = frappe.get_doc("LIMS Label Batch", batch_name)
	existing = frappe.db.count("LIMS Label", {"label_batch": batch_name})
	if existing:
		return int(existing)

	seq = 0
	created = 0
	for item in batch.items:
		for _ in range(int(item.copies or 1) or 1):
			seq += 1
			doc = frappe.new_doc("LIMS Label")
			doc.label_template = batch.label_template
			doc.label_batch = batch_name
			doc.sequence = seq
			doc.reference_doctype = item.reference_doctype
			doc.reference_name = item.reference_name
			doc.barcode = item.barcode or item.reference_name
			doc.status = "Draft"
			doc.insert(ignore_permissions=True)
			created += 1

	log_audit("create_batch_labels", "LIMS Label Batch", batch_name, {"created": created})
	return created


def generate_label_batch_pdf(batch_name: str) -> str:
	"""Render label HTML and attach a single PDF to the batch; return file URL."""
	from frappe.utils.pdf import get_pdf
	from frappe.utils.file_manager import save_file

	batch = frappe.get_doc("LIMS Label Batch", batch_name)
	template = frappe.get_doc("LIMS Label Template", batch.label_template)

	labels = frappe.get_all(
		"LIMS Label",
		filters={"label_batch": batch_name, "status": ["!=", "Cancelled"]},
		fields=["name", "sequence", "reference_doctype", "reference_name", "barcode", "label_template"],
		order_by="sequence asc",
	)
	if not labels:
		frappe.throw("No labels to print")

	css = """
<style>
@page { size: A4; margin: 10mm; }
.label-page { page-break-after: always; }
</style>
""".strip()

	parts: list[str] = ["<html><head>", css, "</head><body>"]
	for row in labels:
		ref_doc = frappe.get_doc(row["reference_doctype"], row["reference_name"])
		ctx: dict[str, Any] = {
			"doc": ref_doc,
			"label": row,
			"batch": batch,
			"printed_on": now_datetime(),
		}
		# Render with Frappe's Jinja env (avoid frappe.render_template logger side effects).
		from frappe.utils.jinja import get_jenv

		inner = get_jenv().from_string(template.template_html or "").render(ctx)
		parts.append(f"<div class='label-page'>{inner}</div>")
	parts.append("</body></html>")
	html = "\n".join(parts)

	pdf_bytes = get_pdf(html)
	f = save_file(
		f"Labels-{batch_name}.pdf",
		pdf_bytes,
		"LIMS Label Batch",
		batch_name,
		is_private=1,
	)

	batch.pdf_file = f.file_url
	batch.save(ignore_permissions=True)
	log_audit("attach_label_batch_pdf", "LIMS Label Batch", batch_name, {"file_url": f.file_url})
	return f.file_url
