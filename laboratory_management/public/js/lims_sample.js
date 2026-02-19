frappe.ui.form.on("LIMS Sample", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button("Load AR Template", () => frm.call("action_load_template").then(() => frm.reload_doc()));
		frm.add_custom_button("Load Sample Template", () => frm.call("action_load_sample_template").then(() => frm.reload_doc()));
		frm.add_custom_button("Load Analysis Profile", () => frm.call("action_load_analysis_profile").then(() => frm.reload_doc()));
		frm.add_custom_button("Hold Sample", () => {
			frappe.prompt(
				[{ fieldname: "reason", label: "Reason", fieldtype: "Small Text", reqd: 1 }],
				(values) => frm.call("action_hold", { reason: values.reason }).then(() => frm.reload_doc()),
				"Hold Sample",
				"Hold"
			);
		});
		frm.add_custom_button("Release Hold", () => frm.call("action_release_hold").then(() => frm.reload_doc()));
		frm.add_custom_button("Mark Sampled", () => frm.call("action_mark_sampled").then(() => frm.reload_doc()));
		frm.add_custom_button("Receive", () => frm.call("action_receive").then(() => frm.reload_doc()));
		frm.add_custom_button("Specimen: Collected", () =>
			frm
				.call("action_register_specimen_event", { event_type: "Collected" })
				.then(() => frm.reload_doc())
		);
		frm.add_custom_button("Specimen: In Transit", () =>
			frm
				.call("action_register_specimen_event", { event_type: "In Transit" })
				.then(() => frm.reload_doc())
		);
		frm.add_custom_button("Specimen: Received", () =>
			frm
				.call("action_register_specimen_event", { event_type: "Received" })
				.then(() => frm.reload_doc())
		);
		frm.add_custom_button("Submit Results", () => frm.call("action_submit_results").then(() => frm.reload_doc()));
		frm.add_custom_button("Verify", () => frm.call("action_verify").then(() => frm.reload_doc()));
		frm.add_custom_button("Publish + COA", () => frm.call("action_publish_with_coa").then(() => frm.reload_doc()));
		frm.add_custom_button("Sign COA (Image/PDF)", () => {
			frappe.prompt(
				[
					{
						fieldname: "signature_file",
						label: "Signature File",
						fieldtype: "Attach",
						reqd: 1,
						description: "Upload image or PDF",
					},
				],
				(values) =>
					frm
						.call("action_sign_coa", { signature_file: values.signature_file })
						.then(() => frm.reload_doc()),
				"Sign COA",
				"Apply"
			);
		});
		frm.add_custom_button("Clear COA Signature", () => frm.call("action_clear_coa_signature").then(() => frm.reload_doc()));
		frm.add_custom_button("Dispatch", () => frm.call("action_dispatch").then(() => frm.reload_doc()));
		frm.add_custom_button("Create Partition", () => {
			frappe.prompt(
				[{ fieldname: "reason", label: "Reason", fieldtype: "Small Text" }],
				(values) => frm.call("action_create_partition", { reason: values.reason || null }).then(() => frm.reload_doc()),
				"Create Partition",
				"Create"
			);
		});
		frm.add_custom_button("Create Sales Order", () => frm.call("action_create_sales_order", { submit_order: 1 }).then(() => frm.reload_doc()));
		frm.add_custom_button("Create Sales Invoice", () => frm.call("action_create_sales_invoice", { submit_invoice: 1 }).then(() => frm.reload_doc()));
		frm.add_custom_button("Create Payment Entry", () => frm.call("action_create_payment_entry", { submit_payment: 1 }).then(() => frm.reload_doc()));
		frm.add_custom_button("Create Credit Note", () => frm.call("action_create_credit_note", { submit_credit_note: 1 }).then(() => frm.reload_doc()));
		frm.add_custom_button("Sync Finance Status", () => frm.call("action_sync_finance_status").then(() => frm.reload_doc()));
		frm.add_custom_button("Acknowledge Critical Result", () => {
			frappe.prompt(
				[
					{ fieldname: "sample_item_row", label: "Sample Item Row ID", fieldtype: "Data", reqd: 1 },
					{ fieldname: "comment", label: "Comment", fieldtype: "Small Text" },
				],
				(values) =>
					frappe.call({
						method:
							"laboratory_management.laboratory_management.doctype.lims_worksheet.lims_worksheet.acknowledge_critical_result",
						args: {
							sample: frm.doc.name,
							sample_item_row: values.sample_item_row,
							comment: values.comment || null,
						},
					}).then(() => frm.reload_doc()),
				"Acknowledge Critical Result",
				"Acknowledge"
			);
		});
		frm.add_custom_button("Acknowledge Delta Result", () => {
			frappe.prompt(
				[
					{ fieldname: "sample_item_row", label: "Sample Item Row ID", fieldtype: "Data", reqd: 1 },
					{ fieldname: "comment", label: "Comment", fieldtype: "Small Text" },
				],
				(values) =>
					frappe.call({
						method:
							"laboratory_management.laboratory_management.doctype.lims_worksheet.lims_worksheet.acknowledge_delta_result",
						args: {
							sample: frm.doc.name,
							sample_item_row: values.sample_item_row,
							comment: values.comment || null,
						},
					}).then(() => frm.reload_doc()),
				"Acknowledge Delta Result",
				"Acknowledge"
			);
		});
		frm.add_custom_button("Generate Interpretation", () =>
			frm.call("action_generate_interpretation").then(() => frm.reload_doc())
		);
		frm.add_custom_button("Authorize Report", () => {
			frappe.prompt(
				[{ fieldname: "final_conclusion", label: "Final Conclusion (Optional)", fieldtype: "Text" }],
				(values) =>
					frm
						.call("action_authorize_report", { final_conclusion: values.final_conclusion || null })
						.then(() => frm.reload_doc()),
				"Authorize Report",
				"Authorize"
			);
		});
		frm.add_custom_button("Log Critical Notification", () => {
			frappe.prompt(
				[
					{ fieldname: "sample_item_row", label: "Sample Item Row ID", fieldtype: "Data", reqd: 1 },
					{ fieldname: "notified_to", label: "Notified To", fieldtype: "Data", reqd: 1 },
					{ fieldname: "notification_channel", label: "Channel", fieldtype: "Select", options: "Phone\nIn Person\nMessage\nOther", default: "Phone" },
					{ fieldname: "readback_confirmed_by", label: "Readback Confirmed By", fieldtype: "Data" },
					{ fieldname: "remarks", label: "Remarks", fieldtype: "Small Text" },
				],
				(values) =>
					frm
						.call("action_log_critical_notification", values)
						.then(() => frm.reload_doc()),
				"Log Critical Notification",
				"Save"
			);
		});

		frm.add_custom_button("Labels PDF", () => {
			frappe.prompt(
				[
					{
						fieldname: "copies",
						fieldtype: "Int",
						label: "Copies",
						default: 1,
						reqd: 1,
					},
					{
						fieldname: "label_template",
						fieldtype: "Link",
						label: "Label Template",
						options: "LIMS Label Template",
						description: "Leave empty to use default Sample label template",
					},
				],
				(values) => {
					frappe
						.call("laboratory_management.api.generate_sample_labels_pdf", {
							sample: frm.doc.name,
							label_template: values.label_template || null,
							copies: values.copies || 1,
						})
						.then((r) => {
							const res = r && r.message;
							if (res && res.file_url) window.open(res.file_url);
						});
				},
				"Generate Labels PDF",
				"Generate"
			);
		});

		frm.add_custom_button("Results Report PDF", () => {
			frappe.prompt(
				[
					{
						fieldname: "print_format",
						fieldtype: "Link",
						label: "Print Format",
						options: "Print Format",
						description: "Leave empty to use LIMS Settings default",
					},
					{
						fieldname: "release",
						fieldtype: "Check",
						label: "Release Report",
						default: 1,
					},
				],
				(values) => {
					frappe
						.call("laboratory_management.api.generate_results_report_pdf", {
							sample: frm.doc.name,
							print_format: values.print_format || null,
							release: values.release ? 1 : 0,
						})
						.then((r) => {
							const res = r && r.message;
							if (res && res.file_url) window.open(res.file_url);
						});
				},
				"Generate Results Report",
				"Generate"
			);
		});
	}
});
