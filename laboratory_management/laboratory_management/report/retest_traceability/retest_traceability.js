frappe.query_reports["Retest Traceability"] = {
	filters: [
		{
			fieldname: "sample",
			label: "Sample",
			fieldtype: "Link",
			options: "LIMS Sample",
		},
		{
			fieldname: "customer",
			label: "Customer",
			fieldtype: "Link",
			options: "Customer",
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
