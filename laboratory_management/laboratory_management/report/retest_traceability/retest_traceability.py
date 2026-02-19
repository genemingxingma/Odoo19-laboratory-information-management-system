from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 140},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "sample_status", "label": "Sample Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 170},
		{"fieldname": "original_item", "label": "Original Item Row", "fieldtype": "Data", "width": 150},
		{"fieldname": "original_status", "label": "Original Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "retest_item", "label": "Retest Item Row", "fieldtype": "Data", "width": 150},
		{"fieldname": "retest_status", "label": "Retest Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "original_result", "label": "Original Result", "fieldtype": "Data", "width": 120},
		{"fieldname": "retest_result", "label": "Retest Result", "fieldtype": "Data", "width": 120},
	]
	return columns, get_data(filters)


def get_data(filters):
	conditions = []
	values = {}

	if filters.sample:
		conditions.append("s.name = %(sample)s")
		values["sample"] = filters.sample
	if filters.customer:
		conditions.append("s.customer = %(customer)s")
		values["customer"] = filters.customer
	if filters.from_date:
		conditions.append("s.creation >= %(from_date)s")
		values["from_date"] = f"{filters.from_date} 00:00:00"
	if filters.to_date:
		conditions.append("s.creation <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"

	where_clause = " and " + " and ".join(conditions) if conditions else ""

	return frappe.db.sql(
		f"""
		select
			s.name as sample,
			s.customer as customer,
			s.sample_status as sample_status,
			orig.analysis_service as analysis_service,
			orig.name as original_item,
			orig.result_status as original_status,
			retest.name as retest_item,
			retest.result_status as retest_status,
			orig.result_value as original_result,
			retest.result_value as retest_result
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` retest on retest.parent = s.name and retest.parenttype = 'LIMS Sample'
		left join `tabLIMS Sample Item` orig on orig.parent = s.name and orig.parenttype = 'LIMS Sample' and retest.retest_of = orig.name
		where coalesce(retest.is_retest, 0) = 1
		{where_clause}
		order by s.creation desc, retest.idx asc
		""",
		values=values,
		as_dict=True,
	)
