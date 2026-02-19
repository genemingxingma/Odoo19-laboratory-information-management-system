frappe.ui.form.on("LIMS Worksheet", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button("Assign Sample", () => {
			frappe.prompt([{fieldname: "sample", label: "Sample", fieldtype: "Link", options: "LIMS Sample", reqd: 1}], (values) => {
				frm.call("action_assign_sample", {sample: values.sample}).then(() => frm.reload_doc());
			}, "Assign Sample", "Assign");
		});
		frm.add_custom_button("Capture Result", () => {
			frappe.prompt(
				[
					{ fieldname: "sample", label: "Sample", fieldtype: "Link", options: "LIMS Sample", reqd: 1 },
					{ fieldname: "sample_item_row", label: "Sample Item Row", fieldtype: "Data", reqd: 1 },
					{ fieldname: "result_value", label: "Result", fieldtype: "Data", reqd: 1 },
					{ fieldname: "instrument", label: "Instrument", fieldtype: "Link", options: "LIMS Instrument" },
				],
				(values) => {
					frappe.call({
						method: "laboratory_management.laboratory_management.doctype.lims_worksheet.lims_worksheet.capture_result",
						args: values,
						callback: () => frm.reload_doc(),
					});
				},
				"Capture Result",
				"Submit"
			);
		});
		frm.add_custom_button("Sync Status", () => frm.call("action_sync_from_samples").then(() => frm.reload_doc()));
		frm.add_custom_button("Close", () => frm.call("action_close").then(() => frm.reload_doc()));
	}
});
