frappe.query_reports["LIMS Financial Overview"] = {
	filters: [
		{
			fieldname: "customer",
			label: "Customer",
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "billing_status",
			label: "Billing Status",
			fieldtype: "Select",
			options: "\nNot Billed\nUnpaid\nPartially Paid\nPaid",
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
