frappe.query_reports["Critical Notification Tracker"] = {
	filters: [
		{ fieldname: "sample", label: "Sample", fieldtype: "Link", options: "LIMS Sample" },
		{ fieldname: "analysis_service", label: "Analysis Service", fieldtype: "Link", options: "LIMS Analysis Service" },
		{ fieldname: "status", label: "Status", fieldtype: "Select", options: "\nOpen\nCompleted" },
		{ fieldname: "from_date", label: "From Date", fieldtype: "Date" },
		{ fieldname: "to_date", label: "To Date", fieldtype: "Date" }
	]
};
