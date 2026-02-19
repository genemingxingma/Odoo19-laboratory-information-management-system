from __future__ import annotations

ITEM_STATUS_DETACHED = {"Rejected", "Retracted"}
ITEM_STATUS_ACTIVE = {"Registered", "Unassigned", "Assigned", "Submitted", "Verified"}


def _active_items(items):
	return [d for d in items if d.result_status in ITEM_STATUS_ACTIVE]


def update_sample_progress(sample_doc):
	items = list(sample_doc.analysis_items or [])
	if not items:
		sample_doc.progress_percent = 0
		return
	progress_map = {"Registered": 10, "Unassigned": 20, "Assigned": 35, "Submitted": 70, "Verified": 100, "Rejected": 100, "Retracted": 100}
	sample_doc.progress_percent = int(sum(progress_map.get(d.result_status or "Registered", 0) for d in items) / len(items))


def recompute_sample_status(sample_doc):
	if sample_doc.sample_status in {"Published", "Dispatched", "Cancelled"}:
		return
	items = list(sample_doc.analysis_items or [])
	if not items:
		sample_doc.sample_status = sample_doc.sample_status or "Draft"
		return
	active = _active_items(items)
	if not active and all(d.result_status in ITEM_STATUS_DETACHED for d in items):
		sample_doc.sample_status = "Rejected"
		return
	statuses = {d.result_status for d in active}
	if statuses <= {"Verified"}:
		sample_doc.sample_status = "Verified"
	elif statuses <= {"Submitted", "Verified"}:
		sample_doc.sample_status = "To Verify"
	elif statuses <= {"Assigned", "Submitted", "Verified", "Unassigned"}:
		sample_doc.sample_status = "Received"


def recompute_worksheet_status(worksheet_doc):
	rows = list(worksheet_doc.worksheet_items or [])
	if not rows:
		worksheet_doc.worksheet_status = "Open"
		return
	statuses = {row.result_status for row in rows}
	if statuses <= {"Verified", "Rejected", "Retracted"}:
		worksheet_doc.worksheet_status = "Verified"
	elif statuses <= {"Submitted", "Verified", "Rejected", "Retracted"}:
		worksheet_doc.worksheet_status = "To Verify"
	else:
		worksheet_doc.worksheet_status = "In Progress"
