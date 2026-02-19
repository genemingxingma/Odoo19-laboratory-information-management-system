from __future__ import annotations

import frappe


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = [
		{"fieldname": "name", "label": "IQC Run", "fieldtype": "Link", "options": "LIMS IQC Run", "width": 130},
		{"fieldname": "run_on", "label": "Run On", "fieldtype": "Datetime", "width": 150},
		{"fieldname": "instrument", "label": "Instrument", "fieldtype": "Link", "options": "LIMS Instrument", "width": 140},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 170},
		{"fieldname": "control_level", "label": "Level", "fieldtype": "Data", "width": 70},
		{"fieldname": "measured_value", "label": "Measured", "fieldtype": "Float", "width": 90},
		{"fieldname": "target_value", "label": "Target", "fieldtype": "Float", "width": 90},
		{"fieldname": "z_score", "label": "Z", "fieldtype": "Float", "width": 70},
		{"fieldname": "westgard_rule", "label": "Rule", "fieldtype": "Data", "width": 80},
		{"fieldname": "qc_status", "label": "Status", "fieldtype": "Data", "width": 80},
		{"fieldname": "message", "label": "Message", "fieldtype": "Data", "width": 220},
	]
	return columns, get_data(filters)


def get_data(filters):
	conds = []
	values = {}
	if filters.instrument:
		conds.append("instrument = %(instrument)s")
		values["instrument"] = filters.instrument
	if filters.analysis_service:
		conds.append("analysis_service = %(analysis_service)s")
		values["analysis_service"] = filters.analysis_service
	if filters.qc_status:
		conds.append("qc_status = %(qc_status)s")
		values["qc_status"] = filters.qc_status
	if filters.from_date:
		conds.append("run_on >= %(from_date)s")
		values["from_date"] = f"{filters.from_date} 00:00:00"
	if filters.to_date:
		conds.append("run_on <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"
	where_clause = " where " + " and ".join(conds) if conds else ""
	return frappe.db.sql(
		f"""
		select name, run_on, instrument, analysis_service, control_level, measured_value, target_value, z_score, westgard_rule, qc_status, message
		from `tabLIMS IQC Run`
		{where_clause}
		order by run_on desc
		""",
		values=values,
		as_dict=True,
	)
