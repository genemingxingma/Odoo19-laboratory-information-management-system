app_name = "laboratory_management"
app_title = "Laboratory Management"
app_publisher = "iMyTest"
app_description = "SENAITE-inspired LIMS for ERPNext"
app_email = "mingxingma@gmail.com"
app_license = "mit"
app_logo_url = "/assets/laboratory_management/images/lims_icon.png"
app_icon = "fa fa-flask"
app_color = "green"

add_to_apps_screen = [
	{
		"name": "laboratory_management",
		# Use PNG for widest compatibility in Desk/app launcher tiles.
		"logo": "/assets/laboratory_management/images/lims_icon.png",
		"title": "Laboratory Management",
		# Frappe requires a route string here; keep it pointing at the workspace slug.
		# The workspace route itself is computed dynamically on migrate in setup.py.
		"route": "/app/laboratory-management",
	}
]

doctype_js = {
	"LIMS Sample": "public/js/lims_sample.js",
	"LIMS Worksheet": "public/js/lims_worksheet.js",
	"LIMS Instrument": "public/js/lims_instrument.js",
	"LIMS Client": "public/js/lims_client.js",
	"LIMS Instrument Message": "public/js/lims_instrument_message.js",
	"LIMS Label Batch": "public/js/lims_label_batch.js",
}

doc_events = {
	"Desktop Layout": {
		"validate": "laboratory_management.desktop_layout.ensure_lims_icon",
	},
	"Sales Invoice": {
		"on_submit": "laboratory_management.event_handlers.on_sales_invoice_change",
		"on_cancel": "laboratory_management.event_handlers.on_sales_invoice_change",
		"on_update_after_submit": "laboratory_management.event_handlers.on_sales_invoice_change",
	},
	"Payment Entry": {
		"on_submit": "laboratory_management.event_handlers.on_payment_entry_change",
		"on_cancel": "laboratory_management.event_handlers.on_payment_entry_change",
		"on_update_after_submit": "laboratory_management.event_handlers.on_payment_entry_change",
	},
}

after_migrate = [
	"laboratory_management.setup.after_migrate",
	"laboratory_management.post_migrate.sync_desktop_icon",
]

scheduler_events = {
	"daily": ["laboratory_management.tasks.daily_maintenance"],
	"hourly": ["laboratory_management.tasks.hourly_maintenance"],
}
