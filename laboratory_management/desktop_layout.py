from __future__ import annotations

import json

import frappe


def ensure_lims_icon(doc, method=None):
	"""Keep Laboratory Management icon present in user desktop layouts."""
	target_label = "Laboratory Management"
	if not frappe.db.exists("Desktop Icon", target_label):
		return

	try:
		layout = json.loads(doc.layout or "[]")
	except Exception:
		layout = []
	if not isinstance(layout, list):
		layout = []

	labels = {item.get("label") for item in layout if isinstance(item, dict)}
	if target_label in labels:
		return

	source = frappe.get_doc("Desktop Icon", target_label).as_dict()
	layout.append(
		{
			"label": source.get("label"),
			"bg_color": source.get("bg_color"),
			"link": source.get("link"),
			"link_type": source.get("link_type"),
			"app": source.get("app"),
			"icon_type": source.get("icon_type"),
			"parent_icon": source.get("parent_icon"),
			"icon": source.get("icon"),
			"link_to": source.get("link_to"),
			"idx": source.get("idx") or 999,
			"standard": source.get("standard"),
			"logo_url": source.get("logo_url"),
			"hidden": source.get("hidden"),
			"name": source.get("name"),
			"restrict_removal": source.get("restrict_removal"),
			"icon_image": source.get("icon_image"),
			"child_icons": [],
		}
	)
	doc.layout = json.dumps(layout)

