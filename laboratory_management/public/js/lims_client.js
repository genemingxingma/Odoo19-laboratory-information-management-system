frappe.ui.form.on("LIMS Client", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button("Sync From Customer", () => frm.call("action_sync_from_customer").then(() => frm.reload_doc()));
	}
});
