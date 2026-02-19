from __future__ import annotations

import frappe


def execute(filters=None):
	columns = [
		{"fieldname": "name", "label": "Message", "fieldtype": "Link", "options": "LIMS Instrument Message", "width": 160},
		{"fieldname": "instrument", "label": "Instrument", "fieldtype": "Link", "options": "LIMS Instrument", "width": 140},
		{"fieldname": "message_type", "label": "Type", "fieldtype": "Data", "width": 80},
		{"fieldname": "parsed_sample_barcode", "label": "Barcode", "fieldtype": "Data", "width": 130},
		{"fieldname": "parsed_service_code", "label": "Service", "fieldtype": "Data", "width": 120},
		{"fieldname": "parsed_result_value", "label": "Result", "fieldtype": "Data", "width": 100},
		{"fieldname": "linked_sample", "label": "Sample", "fieldtype": "Link", "options": "LIMS Sample", "width": 140},
		{"fieldname": "process_status", "label": "Status", "fieldtype": "Data", "width": 90},
		{"fieldname": "modified", "label": "Updated", "fieldtype": "Datetime", "width": 160},
	]
	data = frappe.get_all(
		"LIMS Instrument Message",
		fields=[
			"name",
			"instrument",
			"message_type",
			"parsed_sample_barcode",
			"parsed_service_code",
			"parsed_result_value",
			"linked_sample",
			"process_status",
			"modified",
		],
		order_by="modified desc",
	)
	return columns, data
