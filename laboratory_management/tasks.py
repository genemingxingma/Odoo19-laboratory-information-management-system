from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, nowdate

from laboratory_management.utils import log_audit


def daily_maintenance():
	settings = _get_settings()
	updated_samples = _refresh_sample_tat_flags()
	updated_finance = _refresh_sample_finance_status()
	updated_instruments = _refresh_instrument_overdue_flags()
	calibration_todos = _create_calibration_alert_todos(settings)
	tat_todos = _create_tat_alert_todos(settings)
	critical_todos = _create_critical_result_todos(settings)
	delta_todos = _create_delta_result_todos(settings)
	critical_notify_todos = _create_critical_notification_todos(settings)
	eqa_todos = _create_eqa_due_todos(settings)
	interface_todos = _create_interface_message_todos(settings)
	log_audit(
		"daily_maintenance",
		"LIMS Settings",
		"LIMS Settings",
		{
			"samples_tat_updated": updated_samples,
			"samples_finance_updated": updated_finance,
			"instruments_overdue_updated": updated_instruments,
			"calibration_todos_created": calibration_todos,
			"tat_todos_created": tat_todos,
			"critical_todos_created": critical_todos,
			"delta_todos_created": delta_todos,
			"critical_notification_todos_created": critical_notify_todos,
			"eqa_todos_created": eqa_todos,
			"instrument_message_todos_created": interface_todos,
		},
	)


def hourly_maintenance():
	"""Frequent tasks that keep the lab moving (interface queue, etc.)."""
	settings = _get_settings()
	processed_messages = _process_instrument_message_queue(settings)
	log_audit(
		"hourly_maintenance",
		"LIMS Settings",
		"LIMS Settings",
		{
			"instrument_messages_processed": processed_messages,
		},
	)


def _refresh_sample_tat_flags() -> int:
	today = getdate(nowdate())
	count = 0
	for row in frappe.get_all("LIMS Sample", fields=["name", "due_date", "sample_status", "is_tat_overdue"]):
		overdue = 0
		if row.due_date and row.sample_status not in {"Dispatched", "Cancelled"} and getdate(row.due_date) < today:
			overdue = 1
		if int(row.is_tat_overdue or 0) == overdue:
			continue
		doc = frappe.get_doc("LIMS Sample", row.name)
		doc.is_tat_overdue = overdue
		doc.save(ignore_permissions=True)
		count += 1
	return count


def _refresh_instrument_overdue_flags() -> int:
	today = getdate(nowdate())
	count = 0
	for row in frappe.get_all("LIMS Instrument", fields=["name", "calibration_due_on", "is_calibration_overdue"]):
		overdue = 1 if row.calibration_due_on and getdate(row.calibration_due_on) < today else 0
		if int(row.is_calibration_overdue or 0) == overdue:
			continue
		doc = frappe.get_doc("LIMS Instrument", row.name)
		doc.is_calibration_overdue = overdue
		doc.save(ignore_permissions=True)
		count += 1
	return count


def _refresh_sample_finance_status() -> int:
	count = 0
	for row in frappe.get_all("LIMS Sample", fields=["name"], filters={"sales_invoice": ["is", "set"]}):
		doc = frappe.get_doc("LIMS Sample", row.name)
		before = (doc.billing_status, doc.invoice_outstanding, doc.invoice_paid_amount, doc.payment_status)
		doc._sync_finance_status()
		after = (doc.billing_status, doc.invoice_outstanding, doc.invoice_paid_amount, doc.payment_status)
		if before == after:
			continue
		doc.save(ignore_permissions=True)
		count += 1
	return count


def _get_settings():
	if not frappe.db.exists("DocType", "LIMS Settings"):
		return frappe._dict(
			calibration_alert_days=7,
			tat_alert_days=2,
			alert_owner="Administrator",
			critical_alert_owner=None,
			delta_alert_owner=None,
			instrument_interface_owner=None,
			eqa_alert_days=14,
			instrument_message_auto_process=1,
			instrument_message_batch_size=50,
			instrument_message_retry_max_attempts=5,
			instrument_message_retry_base_minutes=10,
			instrument_message_retry_max_minutes=1440,
		)
	settings = frappe.get_cached_doc("LIMS Settings")
	return frappe._dict(
		calibration_alert_days=int(settings.calibration_alert_days or 7),
		tat_alert_days=int(settings.tat_alert_days or 2),
		alert_owner=settings.alert_owner or "Administrator",
		critical_alert_owner=settings.critical_alert_owner or settings.alert_owner or "Administrator",
		delta_alert_owner=settings.delta_alert_owner or settings.alert_owner or "Administrator",
		instrument_interface_owner=settings.instrument_interface_owner or settings.alert_owner or "Administrator",
		eqa_alert_days=int(settings.eqa_alert_days or 14),
		instrument_message_auto_process=int(getattr(settings, "instrument_message_auto_process", 1) or 0),
		instrument_message_batch_size=int(getattr(settings, "instrument_message_batch_size", 50) or 50),
		instrument_message_retry_max_attempts=int(getattr(settings, "instrument_message_retry_max_attempts", 5) or 5),
		instrument_message_retry_base_minutes=int(getattr(settings, "instrument_message_retry_base_minutes", 10) or 10),
		instrument_message_retry_max_minutes=int(getattr(settings, "instrument_message_retry_max_minutes", 1440) or 1440),
		specifications_enabled=int(getattr(settings, "specifications_enabled", 1) or 0),
	)


def _process_instrument_message_queue(settings) -> int:
	"""Try to parse/import pending instrument messages in the background.

	This is intentionally conservative: it only touches messages that are due for
	retry and respects retry attempt caps from LIMS Settings.
	"""
	if not int(getattr(settings, "instrument_message_auto_process", 1) or 0):
		return 0

	limit = int(getattr(settings, "instrument_message_batch_size", 50) or 50)
	max_attempts = int(getattr(settings, "instrument_message_retry_max_attempts", 5) or 5)
	base_minutes = int(getattr(settings, "instrument_message_retry_base_minutes", 10) or 10)
	max_minutes = int(getattr(settings, "instrument_message_retry_max_minutes", 1440) or 1440)

	# Prefer SQL so we can filter by next_retry_on efficiently.
	rows = frappe.db.sql(
		"""
		select
			name, process_status, coalesce(attempts, 0) as attempts, next_retry_on
		from `tabLIMS Instrument Message`
		where process_status in ('Pending', 'Parsed', 'Failed')
			and coalesce(attempts, 0) < %(max_attempts)s
			and (next_retry_on is null or next_retry_on <= now())
		order by modified asc
		limit %(limit)s
		""",
		{"limit": limit, "max_attempts": max_attempts},
		as_dict=True,
	)
	processed = 0
	for row in rows:
		msg = frappe.get_doc("LIMS Instrument Message", row.name)
		try:
			# Count every processing attempt (including parse) to avoid tight loops.
			msg.attempts = int(msg.attempts or 0) + 1
			msg.last_attempt_on = frappe.utils.now_datetime()
			msg.next_retry_on = None
			msg.save(ignore_permissions=True)

			if msg.process_status == "Pending":
				msg.action_parse()
			if msg.process_status in {"Parsed", "Failed"}:
				msg.action_import_result()
			processed += 1
		except Exception:
			# Exponential-ish backoff with an upper bound. Kept simple and fully
			# controlled by Settings values.
			delay = min(max_minutes, base_minutes * (2 ** max(0, int(msg.attempts or 1) - 1)))
			msg.process_status = "Failed"
			msg.next_retry_on = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=delay)
			msg.save(ignore_permissions=True)
	return processed


def _create_calibration_alert_todos(settings) -> int:
	today = getdate(nowdate())
	threshold = add_days(today, int(settings.calibration_alert_days or 0))
	rows = frappe.get_all(
		"LIMS Instrument",
		fields=["name", "instrument_name", "calibration_due_on", "status", "is_active", "is_calibration_overdue"],
		filters={"is_active": 1},
	)
	created = 0
	for row in rows:
		if row.status != "Active" or not row.calibration_due_on:
			continue
		due = getdate(row.calibration_due_on)
		if due > threshold:
			continue
		is_overdue = int(row.is_calibration_overdue or 0) == 1
		title = "Calibration Overdue" if is_overdue else "Calibration Due Soon"
		desc = (
			f"[LIMS_CAL_ALERT] {title}: {row.instrument_name or row.name} "
			f"(due: {row.calibration_due_on})"
		)
		created += _upsert_todo("LIMS Instrument", row.name, desc, settings.alert_owner, "High" if is_overdue else "Medium")
	return created


def _create_tat_alert_todos(settings) -> int:
	today = getdate(nowdate())
	threshold = add_days(today, int(settings.tat_alert_days or 0))
	rows = frappe.get_all(
		"LIMS Sample",
		fields=["name", "customer", "due_date", "sample_status", "is_tat_overdue"],
		filters={"sample_status": ["not in", ["Dispatched", "Cancelled"]]},
	)
	created = 0
	for row in rows:
		if not row.due_date:
			continue
		due = getdate(row.due_date)
		if due > threshold:
			continue
		is_overdue = int(row.is_tat_overdue or 0) == 1
		title = "TAT Overdue" if is_overdue else "TAT Due Soon"
		desc = (
			f"[LIMS_TAT_ALERT] {title}: Sample {row.name}, "
			f"Customer {row.customer or '-'} (due: {row.due_date})"
		)
		created += _upsert_todo("LIMS Sample", row.name, desc, settings.alert_owner, "High" if is_overdue else "Medium")
	return created


def _create_critical_result_todos(settings) -> int:
	rows = frappe.db.sql(
		"""
		select
			s.name as sample,
			si.name as sample_item_row,
			si.analysis_service,
			si.result_value,
			si.critical_flag
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` si
			on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where coalesce(si.is_critical, 0) = 1
			and coalesce(si.critical_acknowledged, 0) = 0
			and si.result_status in ('Submitted', 'Verified')
		""",
		as_dict=True,
	)
	created = 0
	owner = getattr(settings, "critical_alert_owner", None) or settings.alert_owner
	for row in rows:
		desc = (
			f"[LIMS_CRITICAL] {row.sample}:{row.sample_item_row} "
			f"Critical result for {row.analysis_service} (value={row.result_value}, flag={row.critical_flag or '-'})"
		)
		created += _upsert_todo("LIMS Sample", row.sample, desc, owner, "High")
	return created


def _create_delta_result_todos(settings) -> int:
	rows = frappe.db.sql(
		"""
		select
			s.name as sample,
			si.name as sample_item_row,
			si.analysis_service,
			si.result_value,
			si.previous_result,
			si.delta_percent
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` si
			on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where coalesce(si.is_delta_alert, 0) = 1
			and coalesce(si.delta_acknowledged, 0) = 0
			and si.result_status in ('Submitted', 'Verified')
		""",
		as_dict=True,
	)
	created = 0
	owner = getattr(settings, "delta_alert_owner", None) or settings.alert_owner
	for row in rows:
		desc = (
			f"[LIMS_DELTA] {row.sample}:{row.sample_item_row} "
			f"Delta alert for {row.analysis_service} "
			f"(current={row.result_value}, previous={row.previous_result or '-'}, delta%={row.delta_percent or 0})"
		)
		created += _upsert_todo("LIMS Sample", row.sample, desc, owner, "Medium")
	return created


def _create_critical_notification_todos(settings) -> int:
	rows = frappe.db.sql(
		"""
		select s.name as sample, si.name as sample_item_row, si.analysis_service, si.result_value, si.critical_flag
		from `tabLIMS Sample` s
		inner join `tabLIMS Sample Item` si on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where coalesce(si.is_critical, 0) = 1
			and si.result_status in ('Submitted', 'Verified')
			and not exists (
				select 1
				from `tabLIMS Critical Notification` n
				where n.sample = s.name and n.sample_item_row = si.name and n.status = 'Completed'
			)
		""",
		as_dict=True,
	)
	created = 0
	owner = getattr(settings, "critical_alert_owner", None) or settings.alert_owner
	for row in rows:
		desc = (
			f"[LIMS_CRIT_NOTIFY] {row.sample}:{row.sample_item_row} "
			f"Critical notification pending for {row.analysis_service} "
			f"(value={row.result_value}, flag={row.critical_flag or '-'})"
		)
		created += _upsert_todo("LIMS Sample", row.sample, desc, owner, "High")
	return created


def _create_eqa_due_todos(settings) -> int:
	today = getdate(nowdate())
	threshold = add_days(today, int(settings.eqa_alert_days or 0))
	rows = frappe.get_all(
		"LIMS EQA Plan",
		fields=["name", "plan_title", "due_date", "status", "assigned_to"],
		filters={"status": ["not in", ["Closed"]]},
	)
	created = 0
	for row in rows:
		if not row.due_date:
			continue
		due = getdate(row.due_date)
		if due > threshold:
			continue
		title = "EQA Overdue" if due < today else "EQA Due Soon"
		desc = f"[LIMS_EQA] {title}: {row.name} ({row.plan_title or '-'}) due {row.due_date}"
		owner = row.assigned_to or settings.alert_owner
		created += _upsert_todo("LIMS EQA Plan", row.name, desc, owner, "High" if due < today else "Medium")
	return created


def _create_interface_message_todos(settings) -> int:
	rows = frappe.get_all(
		"LIMS Instrument Message",
		fields=["name", "instrument", "message_type", "process_status"],
		filters={"process_status": ["in", ["Pending", "Failed"]]},
	)
	created = 0
	for row in rows:
		desc = (
			f"[LIMS_IFACE] Message {row.name} "
			f"{row.process_status} ({row.message_type}) instrument={row.instrument or '-'}"
		)
		priority = "High" if row.process_status == "Failed" else "Medium"
		created += _upsert_todo(
			"LIMS Instrument Message",
			row.name,
			desc,
			settings.instrument_interface_owner,
			priority,
		)
	return created


def _upsert_todo(reference_type: str, reference_name: str, description: str, owner: str, priority: str) -> int:
	existing = frappe.get_all(
		"ToDo",
		fields=["name"],
		filters={
			"reference_type": reference_type,
			"reference_name": reference_name,
			"description": ["like", f"%{description.split(':', 1)[0]}%"],
			"status": ["in", ["Open", "Pending"]],
		},
		limit=1,
	)
	if existing:
		return 0
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": owner,
			"priority": priority,
			"status": "Open",
			"description": description,
			"reference_type": reference_type,
			"reference_name": reference_name,
			"date": nowdate(),
		}
	).insert(ignore_permissions=True)
	return 1
