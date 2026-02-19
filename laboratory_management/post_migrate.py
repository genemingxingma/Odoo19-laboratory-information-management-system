from __future__ import annotations

import json

import frappe


def sync_desktop_icon():
	"""Ensure both app icon and desktop entry are present after migrate."""
	_upsert_desktop_icon(
		"Laboratory Management",
		{
			"label": "Laboratory Management",
			"icon_type": "App",
			# Avoid hard-coded /app routes. Link to the workspace sidebar by name.
			"link_type": "Workspace Sidebar",
			"link": "",
			"link_to": "Laboratory Management",
			"icon": "",
			"logo_url": "/assets/laboratory_management/images/lims_icon.png",
			"hidden": 0,
			"app": "laboratory_management",
			"sidebar": "Laboratory Management",
		},
	)

	# Keep desktop entry label different from app title; otherwise Frappe may auto-hide it.
	_upsert_desktop_icon(
		"Laboratory Management Workspace",
		{
			"label": "Laboratory Management Workspace",
			"icon_type": "Link",
			"link_type": "Workspace Sidebar",
			"link_to": "Laboratory Management",
			"icon": "science",
			"logo_url": "",
			"hidden": 0,
			"app": "laboratory_management",
			"sidebar": "Laboratory Management",
		},
	)

	_sync_user_desktop_layouts(["Laboratory Management"])


def _upsert_desktop_icon(name: str, values: dict[str, object]) -> None:
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return

	if frappe.db.exists("Desktop Icon", name):
		frappe.db.set_value("Desktop Icon", name, values, update_modified=False)
		return

	icon = frappe.new_doc("Desktop Icon")
	icon.update({"name": name, "standard": 1, "restrict_removal": 0, **values})
	icon.flags.ignore_permissions = True
	icon.insert(ignore_if_duplicate=True)


def _sync_user_desktop_layouts(icon_labels: list[str]) -> None:
	if not frappe.db.exists("DocType", "Desktop Layout"):
		return

	for user_name in frappe.get_all("Desktop Layout", pluck="name"):
		doc = frappe.get_doc("Desktop Layout", user_name)
		try:
			layout = json.loads(doc.layout or "[]")
		except Exception:
			layout = []
		if not isinstance(layout, list):
			layout = []

		existing = {item.get("label") for item in layout if isinstance(item, dict)}
		changed = False

		for label in icon_labels:
			if label in existing:
				continue
			if not frappe.db.exists("Desktop Icon", label):
				continue

			source = frappe.get_doc("Desktop Icon", label).as_dict()
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
			changed = True

		if changed:
			doc.layout = json.dumps(layout)
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
