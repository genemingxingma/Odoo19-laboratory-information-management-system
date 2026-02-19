from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, nowdate

from laboratory_management.lims_workflow import recompute_sample_status, recompute_worksheet_status, update_sample_progress
from laboratory_management.specifications import check_specification
from laboratory_management.security import ROLE_LIMS_ANALYST, ROLE_LIMS_MANAGER, ROLE_LIMS_VERIFIER, ensure_roles, has_any_role
from laboratory_management.utils import log_audit


class LIMSWorksheet(Document):
	def validate(self):
		recompute_worksheet_status(self)

	@frappe.whitelist()
	def action_assign_sample(self, sample: str):
		ensure_roles(ROLE_LIMS_ANALYST)
		sample_doc = frappe.get_doc("LIMS Sample", sample)
		sample_doc.ensure_not_on_hold()
		if sample_doc.sample_status not in {"Received", "To Verify", "Verified"}:
			frappe.throw("Sample must be at least Received before assigning to worksheet")
		added = 0
		for row in sample_doc.analysis_items:
			if row.result_status not in {"Unassigned", "Assigned"}:
				continue
			if row.result_status == "Assigned" and row.worksheet and row.worksheet != self.name:
				continue
			exists = any(w.sample == sample_doc.name and w.sample_item_row == row.name for w in self.worksheet_items)
			if exists:
				continue
			self.append(
				"worksheet_items",
				{
					"sample": sample_doc.name,
					"sample_item_row": row.name,
					"analysis_service": row.analysis_service,
					"instrument": row.instrument,
					"result_status": "Assigned",
				},
			)
			row.result_status = "Assigned"
			row.worksheet = self.name
			row.analyst = self.analyst or frappe.session.user
			added += 1
		sample_doc.save(ignore_permissions=True)
		self.save()
		log_audit("assign_sample_to_worksheet", "LIMS Worksheet", self.name, {"sample": sample_doc.name, "added": added})
		return {"added": added, "worksheet_status": self.worksheet_status}

	@frappe.whitelist()
	def action_sync_from_samples(self):
		for ws_row in self.worksheet_items:
			sample_doc = frappe.get_doc("LIMS Sample", ws_row.sample)
			matching = [d for d in sample_doc.analysis_items if d.name == ws_row.sample_item_row]
			if matching:
				ws_row.result_status = matching[0].result_status
		recompute_worksheet_status(self)
		self.save()
		log_audit("sync_worksheet_from_samples", "LIMS Worksheet", self.name)
		return self.worksheet_status

	@frappe.whitelist()
	def action_close(self):
		ensure_roles(ROLE_LIMS_VERIFIER)
		if any(row.result_status == "Assigned" for row in self.worksheet_items):
			frappe.throw("Worksheet cannot be closed while assigned items exist")
		if self.worksheet_status not in {"Verified", "Closed", "To Verify"}:
			frappe.throw("Worksheet can only be closed after submission/verification")
		self.worksheet_status = "Closed"
		self.save()
		log_audit("close_worksheet", "LIMS Worksheet", self.name)
		return self.worksheet_status


@frappe.whitelist()
def capture_result(sample: str, sample_item_row: str, result_value: str, instrument: str | None = None):
	ensure_roles(ROLE_LIMS_ANALYST)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	sample_doc.ensure_not_on_hold()
	sample_doc.ensure_not_stability_expired()
	settings = _get_settings()
	if int(settings.enforce_specimen_accession_before_result or 0) and sample_doc.specimen_status not in {
		"Accessioned",
		"Disposed",
	}:
		frappe.throw("Specimen must be accessioned before result capture")
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if row.result_status not in {"Assigned", "Submitted", "Verified"}:
		frappe.throw("Sample item must be assigned before result capture")
	instrument_name = instrument or row.instrument
	if instrument_name:
		_validate_instrument_for_result(instrument_name, row.analysis_service)
		row.instrument = instrument_name
	row.result_value = result_value
	_evaluate_result_flags(sample_doc, row)
	_apply_specifications(sample_doc, row)
	row.result_status = "Submitted"
	row.submitted_by = frappe.session.user
	row.submitted_on = now_datetime()
	sample_doc.sample_status = "To Verify"
	recompute_sample_status(sample_doc)
	update_sample_progress(sample_doc)
	sample_doc.save(ignore_permissions=True)
	_sync_worksheet_row(sample_doc.name, row)
	if int(row.is_critical or 0):
		_create_critical_todo(sample_doc.name, row)
	else:
		_close_critical_todo(sample_doc.name, row.name)
	if int(row.is_delta_alert or 0):
		_create_delta_todo(sample_doc.name, row)
	else:
		_close_delta_todo(sample_doc.name, row.name)
	log_audit("capture_result", "LIMS Sample", sample_doc.name, {"sample_item_row": row.name, "instrument": row.instrument})
	return row.result_status


@frappe.whitelist()
def verify_result(sample: str, sample_item_row: str):
	ensure_roles(ROLE_LIMS_VERIFIER)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if row.result_status != "Submitted":
		frappe.throw("Only submitted results can be verified")

	settings = frappe.get_cached_doc("LIMS Settings") if frappe.db.exists("DocType", "LIMS Settings") else None
	required_verifications = (settings.required_verifications if settings else 1) or 1
	allow_self = settings.allow_self_verification if settings else 0

	if row.submitted_by == frappe.session.user and not (allow_self or has_any_role(ROLE_LIMS_MANAGER)):
		frappe.throw("Self verification is not allowed")

	history = [u.strip() for u in (row.verifier_history or "").split(",") if u.strip()]
	if frappe.session.user in history and not has_any_role(ROLE_LIMS_MANAGER):
		frappe.throw("Consecutive multi verification by same user is not allowed")

	history.append(frappe.session.user)
	row.verification_count = (row.verification_count or 0) + 1
	row.verifier_history = ",".join(history)
	row.verified_by = frappe.session.user
	row.verified_on = now_datetime()

	if row.verification_count >= required_verifications:
		row.result_status = "Verified"
	else:
		row.result_status = "Submitted"

	recompute_sample_status(sample_doc)
	update_sample_progress(sample_doc)
	sample_doc.save(ignore_permissions=True)
	_sync_worksheet_row(sample_doc.name, row)
	log_audit("verify_result", "LIMS Sample", sample_doc.name, {"sample_item_row": row.name, "result_status": row.result_status})
	return {"result_status": row.result_status, "verification_count": row.verification_count, "required": required_verifications}


@frappe.whitelist()
def acknowledge_critical_result(sample: str, sample_item_row: str, comment: str | None = None):
	ensure_roles(ROLE_LIMS_VERIFIER)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if not int(row.is_critical or 0):
		frappe.throw("Only critical results can be acknowledged")

	row.critical_acknowledged = 1
	row.critical_acknowledged_by = frappe.session.user
	row.critical_acknowledged_on = now_datetime()
	row.critical_ack_comment = comment
	sample_doc.save(ignore_permissions=True)
	_close_critical_todo(sample_doc.name, row.name)
	log_audit(
		"acknowledge_critical_result",
		"LIMS Sample",
		sample_doc.name,
		{"sample_item_row": row.name, "analysis_service": row.analysis_service},
	)
	return {
		"critical_acknowledged": row.critical_acknowledged,
		"critical_acknowledged_by": row.critical_acknowledged_by,
		"critical_acknowledged_on": row.critical_acknowledged_on,
	}


@frappe.whitelist()
def acknowledge_delta_result(sample: str, sample_item_row: str, comment: str | None = None):
	ensure_roles(ROLE_LIMS_VERIFIER)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if not int(row.is_delta_alert or 0):
		frappe.throw("Only delta alerts can be acknowledged")

	row.delta_acknowledged = 1
	row.delta_acknowledged_by = frappe.session.user
	row.delta_acknowledged_on = now_datetime()
	row.delta_ack_comment = comment
	sample_doc.save(ignore_permissions=True)
	_close_delta_todo(sample_doc.name, row.name)
	log_audit(
		"acknowledge_delta_result",
		"LIMS Sample",
		sample_doc.name,
		{"sample_item_row": row.name, "analysis_service": row.analysis_service},
	)
	return {
		"delta_acknowledged": row.delta_acknowledged,
		"delta_acknowledged_by": row.delta_acknowledged_by,
		"delta_acknowledged_on": row.delta_acknowledged_on,
	}


@frappe.whitelist()
def reject_result(sample: str, sample_item_row: str, reason: str | None = None, reason_code: str | None = None):
	ensure_roles(ROLE_LIMS_VERIFIER)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if row.result_status in {"Verified", "Retracted"}:
		frappe.throw("Verified or retracted results cannot be rejected")

	settings = frappe.get_cached_doc("LIMS Settings") if frappe.db.exists("DocType", "LIMS Settings") else None
	if settings and settings.rejection_workflow_enabled and not (reason or reason_code):
		frappe.throw("Reason or reason code is required for rejection")

	row.result_status = "Rejected"
	row.rejected_reason = reason or row.rejected_reason
	row.rejected_reason_code = reason_code or row.rejected_reason_code

	recompute_sample_status(sample_doc)
	update_sample_progress(sample_doc)
	sample_doc.save(ignore_permissions=True)
	_sync_worksheet_row(sample_doc.name, row)
	log_audit("reject_result", "LIMS Sample", sample_doc.name, {"sample_item_row": row.name, "reason_code": row.rejected_reason_code})
	return row.result_status


@frappe.whitelist()
def create_retest(sample: str, sample_item_row: str):
	ensure_roles(ROLE_LIMS_MANAGER)
	sample_doc = frappe.get_doc("LIMS Sample", sample)
	row = next((d for d in sample_doc.analysis_items if d.name == sample_item_row), None)
	if not row:
		frappe.throw("Sample item not found")
	if row.result_status not in {"Submitted", "Verified", "Rejected"}:
		frappe.throw("Only submitted/verified/rejected items can be retested")

	new_row = sample_doc.append(
		"analysis_items",
		{
			"analysis_service": row.analysis_service,
			"method": row.method,
			"unit": row.unit,
			"result_status": "Unassigned",
			"retest_of": row.name,
			"is_retest": 1,
		},
	)
	row.result_status = "Retracted"
	sample_doc.sample_status = "Received"
	recompute_sample_status(sample_doc)
	update_sample_progress(sample_doc)
	sample_doc.save(ignore_permissions=True)
	log_audit("create_retest", "LIMS Sample", sample_doc.name, {"source_item": row.name, "new_item": new_row.name})
	return new_row.name


def _sync_worksheet_row(sample_name, sample_row):
	if not sample_row.worksheet:
		return
	ws = frappe.get_doc("LIMS Worksheet", sample_row.worksheet)
	for ws_row in ws.worksheet_items:
		if ws_row.sample == sample_name and ws_row.sample_item_row == sample_row.name:
			ws_row.result_status = sample_row.result_status
			ws_row.instrument = sample_row.instrument
			break
	recompute_worksheet_status(ws)
	ws.save(ignore_permissions=True)


def _validate_instrument_for_result(instrument_name: str, analysis_service: str | None = None):
	instrument = frappe.get_doc("LIMS Instrument", instrument_name)
	if not instrument.is_active or instrument.status != "Active":
		frappe.throw(f"Instrument {instrument_name} is not active")
	if instrument.calibration_due_on and getdate(instrument.calibration_due_on) < getdate(nowdate()):
		frappe.throw(f"Instrument {instrument_name} calibration is overdue")
	settings = _get_settings()
	if int(settings.enforce_iqc_before_result or 0):
		latest = frappe.get_all(
			"LIMS IQC Run",
			filters={"instrument": instrument_name, "analysis_service": analysis_service} if analysis_service else {"instrument": instrument_name},
			fields=["name", "qc_status", "run_on"],
			order_by="run_on desc",
			limit=1,
		)
		if not latest:
			frappe.throw(f"IQC run is required before capturing result on instrument {instrument_name}")
		if latest[0].qc_status == "Fail":
			frappe.throw(f"Latest IQC run {latest[0].name} is FAIL; result capture is blocked")


def _evaluate_result_flags(sample_doc, row):
	settings = _get_settings()
	service = frappe.get_doc("LIMS Analysis Service", row.analysis_service)
	demographics = _get_patient_demographics(sample_doc)
	profile = _resolve_reference_profile(service, demographics)

	row.reference_range = _build_reference_range(profile.get("reference_low"), profile.get("reference_high"), service.unit)
	row.is_abnormal = 0
	row.abnormal_flag = "N"
	row.is_critical = 0
	row.critical_flag = None
	row.critical_acknowledged = 0
	row.critical_acknowledged_by = None
	row.critical_acknowledged_on = None
	row.critical_ack_comment = None
	row.previous_result = None
	row.previous_result_date = None
	row.delta_value = None
	row.delta_percent = None
	row.is_delta_alert = 0
	row.delta_acknowledged = 0
	row.delta_acknowledged_by = None
	row.delta_acknowledged_on = None
	row.delta_ack_comment = None

	if not int(service.is_numeric_result or 0):
		return

	value = _to_float(row.result_value)
	if value is None:
		return

	ref_low = _nullable_float(profile.get("reference_low"))
	ref_high = _nullable_float(profile.get("reference_high"))
	crit_low = _nullable_float(profile.get("critical_low"))
	crit_high = _nullable_float(profile.get("critical_high"))

	if ref_low is not None and value < ref_low:
		row.is_abnormal = 1
		row.abnormal_flag = "L"
	elif ref_high is not None and value > ref_high:
		row.is_abnormal = 1
		row.abnormal_flag = "H"

	if crit_low is not None and value <= crit_low:
		row.is_critical = 1
		row.critical_flag = "LL"
	elif crit_high is not None and value >= crit_high:
		row.is_critical = 1
		row.critical_flag = "HH"

	if int(settings.delta_check_enabled or 0):
		_apply_delta_check(sample_doc, row, value, flt(settings.delta_threshold_percent or 0))


def _apply_specifications(sample_doc, row):
	settings = _get_settings()
	if not int(getattr(settings, "specifications_enabled", 1) or 0):
		row.specification = None
		row.spec_range = None
		row.spec_status = "Not Applicable"
		row.spec_message = None
		return

	res = check_specification(sample_doc, row)
	spec = res.get("spec")
	row.specification = spec.get("name") if spec else None
	row.spec_range = res.get("spec_range")
	row.spec_status = res.get("status") or "Not Applicable"
	row.spec_message = res.get("message")

	if row.spec_status == "Fail" and spec and (spec.get("action_on_fail") or "Warn") == "Block":
		frappe.throw(f"Specification failed ({spec.get('name')}): {row.spec_message or 'Failed'}")


def _apply_delta_check(sample_doc, row, current_value: float, threshold_percent: float):
	if not sample_doc.patient:
		return
	previous = _get_previous_numeric_result(sample_doc, row.analysis_service)
	if not previous:
		return

	previous_value = previous.get("value")
	if previous_value is None:
		return
	row.previous_result = f"{previous_value:g}"
	row.previous_result_date = previous.get("result_time")
	row.delta_value = current_value - previous_value
	if previous_value != 0:
		row.delta_percent = abs((current_value - previous_value) / previous_value) * 100
	if row.delta_percent is not None and row.delta_percent >= threshold_percent:
		row.is_delta_alert = 1


def _get_previous_numeric_result(sample_doc, analysis_service: str):
	rows = frappe.db.sql(
		"""
		select
			si.result_value,
			coalesce(si.verified_on, si.submitted_on, s.modified) as result_time
		from `tabLIMS Sample Item` si
		inner join `tabLIMS Sample` s
			on si.parent = s.name and si.parenttype = 'LIMS Sample'
		where s.patient = %(patient)s
			and si.analysis_service = %(analysis_service)s
			and si.result_status = 'Verified'
			and s.name != %(sample_name)s
		order by coalesce(si.verified_on, si.submitted_on, s.modified) desc
		limit 20
		""",
		values={
			"patient": sample_doc.patient,
			"analysis_service": analysis_service,
			"sample_name": sample_doc.name,
		},
		as_dict=True,
	)
	for row in rows:
		value = _to_float(row.result_value)
		if value is None:
			continue
		return {"value": value, "result_time": row.result_time}
	return None


def _get_patient_demographics(sample_doc):
	if not sample_doc.patient or not frappe.db.exists("Patient", sample_doc.patient):
		return {"sex": "Unknown", "age_years": None}

	meta = frappe.get_meta("Patient")
	fields = []
	if meta.has_field("sex"):
		fields.append("sex")
	if meta.has_field("dob"):
		fields.append("dob")
	if meta.has_field("date_of_birth"):
		fields.append("date_of_birth")
	values = frappe.db.get_value("Patient", sample_doc.patient, fields, as_dict=True) if fields else {}
	sex_raw = (values.get("sex") or "").strip().lower() if values else ""
	if sex_raw in {"male", "m"}:
		sex = "Male"
	elif sex_raw in {"female", "f"}:
		sex = "Female"
	else:
		sex = "Unknown"

	dob = values.get("dob") if values and "dob" in values else values.get("date_of_birth") if values else None
	age_years = None
	if dob:
		reference_date = sample_doc.collection_datetime or sample_doc.received_datetime or nowdate()
		age_years = (getdate(reference_date) - getdate(dob)).days / 365.25
	return {"sex": sex, "age_years": age_years}


def _resolve_reference_profile(service_doc, demographics):
	profile = {
		"reference_low": service_doc.reference_low,
		"reference_high": service_doc.reference_high,
		"critical_low": service_doc.critical_low,
		"critical_high": service_doc.critical_high,
	}
	sex = demographics.get("sex")
	age_years = demographics.get("age_years")
	for rule in service_doc.reference_rules or []:
		if not _reference_rule_matches(rule, sex, age_years):
			continue
		profile = {
			"reference_low": rule.reference_low,
			"reference_high": rule.reference_high,
			"critical_low": rule.critical_low,
			"critical_high": rule.critical_high,
		}
		break
	return profile


def _reference_rule_matches(rule, sex: str, age_years: float | None):
	rule_sex = (rule.sex or "Any").strip()
	if rule_sex != "Any" and rule_sex != sex:
		return False
	if age_years is None:
		if rule.age_min_years is not None or rule.age_max_years is not None:
			return False
		return True
	if rule.age_min_years is not None and age_years < flt(rule.age_min_years):
		return False
	if rule.age_max_years is not None and age_years > flt(rule.age_max_years):
		return False
	return True


def _to_float(value):
	try:
		if value is None:
			return None
		text = str(value).strip()
		if not text:
			return None
		return float(text)
	except Exception:
		return None


def _nullable_float(value):
	if value in (None, "", "None"):
		return None
	return flt(value)


def _build_reference_range(reference_low, reference_high, unit: str | None) -> str | None:
	ref_low = _nullable_float(reference_low)
	ref_high = _nullable_float(reference_high)
	if ref_low is None and ref_high is None:
		return None
	unit_text = unit or ""
	if ref_low is not None and ref_high is not None:
		return f"{ref_low:g} - {ref_high:g} {unit_text}".strip()
	if ref_low is not None:
		return f">= {ref_low:g} {unit_text}".strip()
	return f"<= {ref_high:g} {unit_text}".strip()


def _get_settings():
	if not frappe.db.exists("DocType", "LIMS Settings"):
		return frappe._dict(
			delta_check_enabled=1,
			delta_threshold_percent=30,
			critical_alert_owner="Administrator",
			delta_alert_owner="Administrator",
			enforce_iqc_before_result=1,
			enforce_specimen_accession_before_result=1,
			alert_owner="Administrator",
		)
	settings = frappe.get_cached_doc("LIMS Settings")
	return frappe._dict(
		delta_check_enabled=int(settings.delta_check_enabled or 0),
		delta_threshold_percent=flt(settings.delta_threshold_percent or 30),
		critical_alert_owner=settings.critical_alert_owner or settings.alert_owner or "Administrator",
		delta_alert_owner=settings.delta_alert_owner or settings.alert_owner or "Administrator",
		enforce_iqc_before_result=int(settings.enforce_iqc_before_result or 0),
		enforce_specimen_accession_before_result=int(settings.enforce_specimen_accession_before_result or 0),
		alert_owner=settings.alert_owner or "Administrator",
	)


def _create_critical_todo(sample: str, row):
	settings = _get_settings()
	owner = settings.critical_alert_owner
	tag = f"[LIMS_CRITICAL] {sample}:{row.name}"
	exists = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"description": ["like", f"%{tag}%"],
			"status": ["in", ["Open", "Pending"]],
		},
		pluck="name",
		limit=1,
	)
	if exists:
		return
	description = (
		f"{tag} Critical result for {row.analysis_service} "
		f"(value={row.result_value}, flag={row.critical_flag or '-'})"
	)
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": owner,
			"priority": "High",
			"status": "Open",
			"description": description,
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"date": nowdate(),
		}
	).insert(ignore_permissions=True)


def _close_critical_todo(sample: str, sample_item_row: str):
	tag = f"[LIMS_CRITICAL] {sample}:{sample_item_row}"
	rows = frappe.get_all(
		"ToDo",
		fields=["name", "status"],
		filters={
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"description": ["like", f"%{tag}%"],
			"status": ["in", ["Open", "Pending"]],
		},
	)
	for todo in rows:
		doc = frappe.get_doc("ToDo", todo.name)
		doc.status = "Closed"
		doc.save(ignore_permissions=True)


def _create_delta_todo(sample: str, row):
	settings = _get_settings()
	owner = settings.delta_alert_owner
	tag = f"[LIMS_DELTA] {sample}:{row.name}"
	exists = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"description": ["like", f"%{tag}%"],
			"status": ["in", ["Open", "Pending"]],
		},
		pluck="name",
		limit=1,
	)
	if exists:
		return
	description = (
		f"{tag} Delta alert for {row.analysis_service} "
		f"(current={row.result_value}, previous={row.previous_result or '-'}, delta%={row.delta_percent or 0:.2f})"
	)
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": owner,
			"priority": "Medium",
			"status": "Open",
			"description": description,
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"date": nowdate(),
		}
	).insert(ignore_permissions=True)


def _close_delta_todo(sample: str, sample_item_row: str):
	tag = f"[LIMS_DELTA] {sample}:{sample_item_row}"
	rows = frappe.get_all(
		"ToDo",
		fields=["name", "status"],
		filters={
			"reference_type": "LIMS Sample",
			"reference_name": sample,
			"description": ["like", f"%{tag}%"],
			"status": ["in", ["Open", "Pending"]],
		},
	)
	for todo in rows:
		doc = frappe.get_doc("ToDo", todo.name)
		doc.status = "Closed"
		doc.save(ignore_permissions=True)
