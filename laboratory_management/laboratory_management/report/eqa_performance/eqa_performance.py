from __future__ import annotations

import frappe


def execute(filters=None):
	columns = [
		{"fieldname": "eqa_plan", "label": "EQA Plan", "fieldtype": "Link", "options": "LIMS EQA Plan", "width": 150},
		{"fieldname": "analysis_service", "label": "Analysis Service", "fieldtype": "Link", "options": "LIMS Analysis Service", "width": 160},
		{"fieldname": "instrument", "label": "Instrument", "fieldtype": "Link", "options": "LIMS Instrument", "width": 140},
		{"fieldname": "reported_value", "label": "Reported", "fieldtype": "Data", "width": 100},
		{"fieldname": "z_score", "label": "Z Score", "fieldtype": "Float", "width": 90},
		{"fieldname": "score_percent", "label": "Score %", "fieldtype": "Percent", "width": 90},
		{"fieldname": "evaluation", "label": "Evaluation", "fieldtype": "Data", "width": 90},
		{"fieldname": "evaluated_on", "label": "Evaluated On", "fieldtype": "Datetime", "width": 160},
	]
	data = frappe.get_all(
		"LIMS EQA Result",
		fields=[
			"eqa_plan",
			"analysis_service",
			"instrument",
			"reported_value",
			"z_score",
			"score_percent",
			"evaluation",
			"evaluated_on",
		],
		order_by="modified desc",
	)
	return columns, data
