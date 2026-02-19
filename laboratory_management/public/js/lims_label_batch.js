frappe.ui.form.on("LIMS Label Batch", {
	refresh(frm) {
		if (frm.doc.status === "Cancelled") return;

		frm.add_custom_button("Generate PDF", () => {
			frm.call("action_generate_pdf").then((r) => {
				const url = r && r.message;
				if (url) window.open(url);
				frm.reload_doc();
			});
		});

		frm.add_custom_button("Mark Printed", () => {
			frm.call("action_mark_printed").then(() => frm.reload_doc());
		});

		frm.add_custom_button("Cancel", () => {
			frappe.confirm("Cancel this label batch?", () => {
				frm.call("action_cancel").then(() => frm.reload_doc());
			});
		});
	},
});

