from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 140},
		{"fieldname": "sample_status", "label": "Sample Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "width": 140},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 180},
		{"fieldname": "result_value", "label": "Result", "fieldtype": "Data", "width": 100},
		{"fieldname": "reference_range", "label": "Reference Range", "fieldtype": "Data", "width": 130},
		{"fieldname": "critical_flag", "label": "Critical Flag", "fieldtype": "Data", "width": 90},
		{"fieldname": "critical_acknowledged", "label": "Acknowledged", "fieldtype": "Check", "width": 90},
		{"fieldname": "critical_acknowledged_by", "label": "Acknowledged By", "fieldtype": "Link", "options": "User", "width": 130},
		{"fieldname": "critical_acknowledged_on", "label": "Acknowledged On", "fieldtype": "Datetime", "width": 160},
		{"fieldname": "submitted_on", "label": "Submitted On", "fieldtype": "Datetime", "width": 160},
	]
	return columns, get_data(filters)


def get_data(filters):
	conditions = ["coalesce(si.is_critical, 0) = 1"]
	values = {}

	if filters.sample:
		conditions.append("s.name = %(sample)s")
		values["sample"] = filters.sample
	if filters.analysis_service:
		conditions.append("si.analysis_service = %(analysis_service)s")
		values["analysis_service"] = filters.analysis_service
	if filters.acknowledged == "Yes":
		conditions.append("coalesce(si.critical_acknowledged, 0) = 1")
	elif filters.acknowledged == "No":
		conditions.append("coalesce(si.critical_acknowledged, 0) = 0")
	if filters.from_date:
		conditions.append("s.creation >= %(from_date)s")
		values["from_date"] = f"{filters.from_date} 00:00:00"
	if filters.to_date:
		conditions.append("s.creation <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"

	where_clause = " and ".join(conditions)
	return frappe.db.sql(
		f"""
		select
			s.name as sample,
			s.sample_status,
			s.customer,
			si.analysis_service,
			si.result_value,
			si.reference_range,
			si.critical_flag,
			si.critical_acknowledged,
			si.critical_acknowledged_by,
			si.critical_acknowledged_on,
			si.submitted_on
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` si
			on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where {where_clause}
		order by coalesce(si.critical_acknowledged, 0) asc, si.submitted_on desc, s.modified desc
		""",
		values=values,
		as_dict=True,
	)
