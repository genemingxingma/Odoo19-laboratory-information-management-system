from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 140},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "sample_status", "label": "Sample Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "sales_invoice", "label": "Sales Invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"fieldname": "credit_note", "label": "Credit Note", "fieldtype": "Link", "options": "Sales Invoice", "width": 140},
		{"fieldname": "payment_entry", "label": "Payment Entry", "fieldtype": "Link", "options": "Payment Entry", "width": 140},
		{"fieldname": "billing_status", "label": "Billing Status", "fieldtype": "Data", "width": 120},
		{"fieldname": "invoice_grand_total", "label": "Grand Total", "fieldtype": "Currency", "width": 120},
		{"fieldname": "invoice_outstanding", "label": "Outstanding", "fieldtype": "Currency", "width": 120},
		{"fieldname": "invoice_paid_amount", "label": "Paid", "fieldtype": "Currency", "width": 120},
	]
	return columns, get_data(filters)


def get_data(filters):
	conditions = []
	values = {}

	if filters.customer:
		conditions.append("customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.billing_status:
		conditions.append("billing_status = %(billing_status)s")
		values["billing_status"] = filters.billing_status
	if filters.from_date:
		conditions.append("creation >= %(from_date)s")
		values["from_date"] = f"{filters.from_date} 00:00:00"
	if filters.to_date:
		conditions.append("creation <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"

	where_clause = " where " + " and ".join(conditions) if conditions else ""

	return frappe.db.sql(
		f"""
		select
			name as sample,
			customer,
			sample_status,
			sales_invoice,
			credit_note,
			payment_entry,
			billing_status,
			invoice_grand_total,
			invoice_outstanding,
			invoice_paid_amount
		from `tabLIMS Sample`
		{where_clause}
		order by modified desc
		""",
		values=values,
		as_dict=True,
	)
