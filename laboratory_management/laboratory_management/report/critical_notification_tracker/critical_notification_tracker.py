from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": "Notification", "fieldtype": "Link", "options": "LIMS Critical Notification", "width": 130},
		{"fieldname": "sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 130},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 170},
		{"fieldname": "result_value", "label": "Result", "fieldtype": "Data", "width": 90},
		{"fieldname": "critical_flag", "label": "Flag", "fieldtype": "Data", "width": 70},
		{"fieldname": "notified_to", "label": "Notified To", "fieldtype": "Data", "width": 140},
		{"fieldname": "notified_on", "label": "Notified On", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "readback_confirmed_by", "label": "Readback By", "fieldtype": "Data", "width": 120},
		{"fieldname": "readback_confirmed_on", "label": "Readback On", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 90},
	]
	return columns, get_data(filters)


def get_data(filters):
	conds = []
	values = {}
	if filters.sample:
		conds.append("sample = %(sample)s")
		values["sample"] = filters.sample
	if filters.analysis_service:
		conds.append("analysis_service = %(analysis_service)s")
		values["analysis_service"] = filters.analysis_service
	if filters.status:
		conds.append("status = %(status)s")
		values["status"] = filters.status
	if filters.from_date:
		conds.append("notified_on >= %(from_date)s")
		values["from_date"] = f"{filters.from_date} 00:00:00"
	if filters.to_date:
		conds.append("notified_on <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"
	where_clause = " where " + " and ".join(conds) if conds else ""
	return frappe.db.sql(
		f"""
		select name, sample, analysis_service, result_value, critical_flag, notified_to, notified_on, readback_confirmed_by, readback_confirmed_on, status
		from `tabLIMS Critical Notification`
		{where_clause}
		order by notified_on desc
		""",
		values=values,
		as_dict=True,
	)
