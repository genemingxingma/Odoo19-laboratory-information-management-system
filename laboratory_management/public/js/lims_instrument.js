frappe.ui.form.on("LIMS Instrument", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button("Sync From Asset", () => frm.call("action_sync_from_asset").then(() => frm.reload_doc()));
		frm.add_custom_button("Push Calibration To Asset", () => frm.call("action_push_calibration_to_asset").then(() => frm.reload_doc()));
	}
});
