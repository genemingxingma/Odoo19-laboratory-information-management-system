frappe.query_reports["Delta Check Monitor"] = {
	filters: [
		{
			fieldname: "sample",
			label: "Sample",
			fieldtype: "Link",
			options: "LIMS Sample",
		},
		{
			fieldname: "analysis_service",
			label: "Analysis Service",
			fieldtype: "Link",
			options: "LIMS Analysis Service",
		},
		{
			fieldname: "acknowledged",
			label: "Acknowledged",
			fieldtype: "Select",
			options: "\nNo\nYes",
		},
		{
			fieldname: "from_date",
			label: "From Date",
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: "To Date",
			fieldtype: "Date",
		},
	],
};
