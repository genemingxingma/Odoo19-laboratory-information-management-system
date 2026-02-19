frappe.ui.form.on("LIMS Instrument Message", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button("Parse", () => frm.call("action_parse").then(() => frm.reload_doc()));
		frm.add_custom_button("Import Result", () => frm.call("action_import_result").then(() => frm.reload_doc()));
	}
});
