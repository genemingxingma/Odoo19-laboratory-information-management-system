from __future__ import annotations

import frappe

from laboratory_management.utils import log_audit


def on_sales_invoice_change(doc, _method=None):
	invoice_names = {doc.name}
	return_against = getattr(doc, "return_against", None)
	if return_against:
		invoice_names.add(return_against)
	_sync_samples_for_invoices(invoice_names, f"sales_invoice:{doc.name}")


def on_payment_entry_change(doc, _method=None):
	invoice_names = set()
	for row in (doc.references or []):
		if row.reference_doctype == "Sales Invoice" and row.reference_name:
			invoice_names.add(row.reference_name)
	_sync_samples_for_invoices(invoice_names, f"payment_entry:{doc.name}")


def _sync_samples_for_invoices(invoice_names: set[str], reason: str):
	if not invoice_names:
		return

	invoices = list(invoice_names)
	sample_names = set(
		frappe.get_all("LIMS Sample", filters={"sales_invoice": ["in", invoices]}, pluck="name")
	)
	sample_names.update(
		frappe.get_all("LIMS Sample", filters={"credit_note": ["in", invoices]}, pluck="name")
	)
	if not sample_names:
		return

	for sample_name in sorted(sample_names):
		try:
			doc = frappe.get_doc("LIMS Sample", sample_name)
			before = (
				doc.billing_status,
				doc.payment_status,
				doc.invoice_grand_total,
				doc.invoice_outstanding,
				doc.invoice_paid_amount,
			)
			doc._sync_finance_status()
			after = (
				doc.billing_status,
				doc.payment_status,
				doc.invoice_grand_total,
				doc.invoice_outstanding,
				doc.invoice_paid_amount,
			)
			if before != after:
				doc.save(ignore_permissions=True)
			log_audit(
				"finance_event_sync",
				"LIMS Sample",
				doc.name,
				{
					"reason": reason,
					"billing_status": doc.billing_status,
					"payment_status": doc.payment_status,
					"outstanding": doc.invoice_outstanding,
				},
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"LIMS finance sync failed for {sample_name}")
