frappe.query_reports["IQC Monitor"] = {
	filters: [
		{ fieldname: "instrument", label: "Instrument", fieldtype: "Link", options: "LIMS Instrument" },
		{ fieldname: "analysis_service", label: "Analysis Service", fieldtype: "Link", options: "LIMS Analysis Service" },
		{ fieldname: "qc_status", label: "QC Status", fieldtype: "Select", options: "\nPass\nWarning\nFail" },
		{ fieldname: "from_date", label: "From Date", fieldtype: "Date" },
		{ fieldname: "to_date", label: "To Date", fieldtype: "Date" }
	]
};
