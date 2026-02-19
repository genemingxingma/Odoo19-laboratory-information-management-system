from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 140},
		{"fieldname": "sample_status", "label": "Sample Status", "fieldtype": "Data", "width": 110},
		{"fieldname": "patient", "label": "Patient", "fieldtype": "Link", "options": "Patient", "width": 130},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 180},
		{"fieldname": "result_value", "label": "Current", "fieldtype": "Data", "width": 90},
		{"fieldname": "previous_result", "label": "Previous", "fieldtype": "Data", "width": 90},
		{"fieldname": "delta_value", "label": "Delta Value", "fieldtype": "Float", "width": 110},
		{"fieldname": "delta_percent", "label": "Delta %", "fieldtype": "Percent", "width": 100},
		{"fieldname": "delta_acknowledged", "label": "Acknowledged", "fieldtype": "Check", "width": 95},
		{"fieldname": "delta_acknowledged_by", "label": "Acknowledged By", "fieldtype": "Link", "options": "User", "width": 130},
		{"fieldname": "delta_acknowledged_on", "label": "Acknowledged On", "fieldtype": "Datetime", "width": 160},
	]
	return columns, get_data(filters)


def get_data(filters):
	conditions = ["coalesce(si.is_delta_alert, 0) = 1"]
	values = {}

	if filters.sample:
		conditions.append("s.name = %(sample)s")
		values["sample"] = filters.sample
	if filters.analysis_service:
		conditions.append("si.analysis_service = %(analysis_service)s")
		values["analysis_service"] = filters.analysis_service
	if filters.acknowledged == "Yes":
		conditions.append("coalesce(si.delta_acknowledged, 0) = 1")
	elif filters.acknowledged == "No":
		conditions.append("coalesce(si.delta_acknowledged, 0) = 0")
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
			s.patient,
			si.analysis_service,
			si.result_value,
			si.previous_result,
			si.delta_value,
			si.delta_percent,
			si.delta_acknowledged,
			si.delta_acknowledged_by,
			si.delta_acknowledged_on
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` si
			on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where {where_clause}
		order by coalesce(si.delta_acknowledged, 0) asc, si.delta_percent desc, s.modified desc
		""",
		values=values,
		as_dict=True,
	)
