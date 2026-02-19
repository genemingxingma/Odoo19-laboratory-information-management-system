from __future__ import annotations

import frappe
from frappe.utils import add_to_date, now_datetime

from laboratory_management.laboratory_management.doctype.lims_worksheet import lims_worksheet


def run_medical_smoke_test() -> dict:
	frappe.set_user("Administrator")
	result = {"checks": {}, "artifacts": {}}

	settings = frappe.get_single("LIMS Settings")
	old_settings = {
		"enforce_iqc_before_result": settings.enforce_iqc_before_result,
		"require_critical_ack_on_publish": settings.require_critical_ack_on_publish,
		"require_delta_ack_on_publish": settings.require_delta_ack_on_publish,
		"require_critical_notification_on_publish": settings.require_critical_notification_on_publish,
		"require_report_authorization_on_publish": settings.require_report_authorization_on_publish,
		"delta_check_enabled": settings.delta_check_enabled,
		"delta_threshold_percent": settings.delta_threshold_percent,
		"enforce_specimen_accession_before_result": settings.enforce_specimen_accession_before_result,
		"enable_specimen_barcode_check": settings.enable_specimen_barcode_check,
		"eqa_alert_days": settings.eqa_alert_days,
		"alert_owner": settings.alert_owner,
		"critical_alert_owner": settings.critical_alert_owner,
		"delta_alert_owner": settings.delta_alert_owner,
		"instrument_interface_owner": settings.instrument_interface_owner,
	}

	try:
		settings.enforce_iqc_before_result = 1
		settings.require_critical_ack_on_publish = 1
		settings.require_delta_ack_on_publish = 0
		settings.require_critical_notification_on_publish = 1
		settings.require_report_authorization_on_publish = 1
		settings.delta_check_enabled = 1
		settings.delta_threshold_percent = 30
		settings.enforce_specimen_accession_before_result = 1
		settings.enable_specimen_barcode_check = 1
		settings.eqa_alert_days = 14
		settings.alert_owner = "Administrator"
		settings.critical_alert_owner = "Administrator"
		settings.delta_alert_owner = "Administrator"
		settings.instrument_interface_owner = "Administrator"
		settings.save(ignore_permissions=True)

		_get_or_create_master_data()
		sample_type = _get_or_create_sample_type()
		service = _get_or_create_analysis_service()
		instrument = _get_or_create_instrument()
		patient = _get_or_create_patient()
		tpl = _get_or_create_interpretation_template(service)

		result["artifacts"]["sample_type"] = sample_type
		result["artifacts"]["analysis_service"] = service
		result["artifacts"]["instrument"] = instrument
		result["artifacts"]["patient"] = patient
		result["artifacts"]["interpretation_template"] = tpl

		ws = _create_worksheet(analyst="Administrator")

		first_sample = _create_sample(sample_type, service, patient)
		if first_sample.sample_template:
			first_sample.action_load_sample_template()
			first_sample.reload()
		first_sample.action_receive()
		first_sample.action_register_specimen_event("Collected")
		first_sample.action_register_specimen_event("Received")
		ws.action_assign_sample(first_sample.name)
		first_sample.reload()
		first_row = _first_row(first_sample)
		_create_iqc_run(instrument, service, measured=10.0, target=10.0, sd=2.0)
		lims_worksheet.capture_result(first_sample.name, first_row.name, "10", instrument=instrument)
		lims_worksheet.verify_result(first_sample.name, first_row.name)
		first_sample.reload()
		result["checks"]["first_sample_verified"] = first_sample.sample_status == "Verified"

		second_sample = _create_sample(sample_type, service, patient)
		if second_sample.sample_template:
			second_sample.action_load_sample_template()
			second_sample.reload()
		second_sample.action_receive()
		second_sample.action_register_specimen_event("Collected")
		second_sample.action_register_specimen_event("In Transit")
		second_sample.action_register_specimen_event("Received")
		ws.action_assign_sample(second_sample.name)
		second_sample.reload()
		second_row = _first_row(second_sample)

		t0 = now_datetime()
		_create_iqc_run(instrument, service, measured=20.0, target=10.0, sd=2.0, run_on=t0)
		blocked_by_iqc = False
		try:
			lims_worksheet.capture_result(second_sample.name, second_row.name, "25", instrument=instrument)
		except Exception as e:
			blocked_by_iqc = "IQC" in str(e) or "FAIL" in str(e)
		result["checks"]["iqc_fail_blocks_capture"] = blocked_by_iqc

		_create_iqc_run(
			instrument,
			service,
			measured=13.0,
			target=10.0,
			sd=2.0,
			run_on=add_to_date(t0, minutes=1),
		)
		lims_worksheet.capture_result(second_sample.name, second_row.name, "25", instrument=instrument)
		lims_worksheet.verify_result(second_sample.name, second_row.name)
		second_sample.reload()
		second_row = _first_row(second_sample)
		result["checks"]["critical_flagged"] = int(second_row.is_critical or 0) == 1
		result["checks"]["delta_flagged_or_not_applicable"] = int(second_row.is_delta_alert or 0) == 1 or not patient

		publish_blocked_initial = False
		try:
			second_sample.action_publish()
		except Exception:
			publish_blocked_initial = True
		result["checks"]["publish_blocked_before_acks"] = publish_blocked_initial

		lims_worksheet.acknowledge_critical_result(second_sample.name, second_row.name, "Reviewed")
		if int(second_row.is_delta_alert or 0):
			lims_worksheet.acknowledge_delta_result(second_sample.name, second_row.name, "Reviewed")
		second_sample.reload()
		notification = second_sample.action_log_critical_notification(
			sample_item_row=second_row.name,
			notified_to="Ward Doctor",
			notification_channel="Phone",
			readback_confirmed_by="Ward Doctor",
			remarks="Readback complete",
		)
		second_sample.action_generate_interpretation()
		second_sample.action_authorize_report()
		second_sample.reload()
		second_sample.action_publish()
		second_sample.reload()

		result["checks"]["notification_logged"] = bool(notification)
		result["checks"]["report_authorized"] = int(second_sample.is_report_authorized or 0) == 1
		result["checks"]["published_after_all_requirements"] = second_sample.sample_status == "Published"
		result["checks"]["interpretation_generated"] = bool(second_sample.preliminary_conclusion)
		result["checks"]["specimen_accessioned"] = second_sample.specimen_status == "Accessioned"

		eqa_plan = _create_eqa_plan(service, instrument)
		eqa_result = _create_eqa_result(eqa_plan, service, second_sample, instrument)
		result["checks"]["eqa_recorded"] = bool(eqa_result)

		msg = _create_hl7_message(instrument, second_sample.sample_barcode, service, "12.5")
		msg.action_import_result()
		msg.reload()
		result["checks"]["instrument_message_processed"] = msg.process_status == "Processed"

		result["artifacts"]["first_sample"] = first_sample.name
		result["artifacts"]["second_sample"] = second_sample.name
		result["artifacts"]["critical_notification"] = notification
		result["artifacts"]["eqa_plan"] = eqa_plan
		result["artifacts"]["eqa_result"] = eqa_result
		result["artifacts"]["instrument_message"] = msg.name

		result["ok"] = all(result["checks"].values())
		frappe.db.commit()
		return result
	finally:
		settings = frappe.get_single("LIMS Settings")
		for k, v in old_settings.items():
			setattr(settings, k, v)
		settings.save(ignore_permissions=True)
		frappe.db.commit()


def _get_or_create_sample_type() -> str:
	name = "TEST-ST"
	if not frappe.db.exists("LIMS Sample Type", name):
		doc = frappe.new_doc("LIMS Sample Type")
		doc.sample_type_name = name
		doc.code = name
		doc.insert(ignore_permissions=True)
	return name


def _get_or_create_master_data():
	# Minimal master data coverage for SENAITE parity set.
	# Some master docs depend on Sample Type links (e.g. Sample Template).
	_get_or_create_sample_type()

	if not frappe.db.exists("LIMS Department", "TEST-DEP"):
		d = frappe.new_doc("LIMS Department")
		d.department_name = "TEST-DEP"
		d.code = "TEST-DEP"
		d.is_active = 1
		d.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Container Type", "TEST-TUBE"):
		ct = frappe.new_doc("LIMS Container Type")
		ct.container_type_name = "TEST-TUBE"
		ct.code = "TEST-TUBE"
		ct.material = "Plastic"
		ct.capacity_ml = 5
		ct.is_active = 1
		ct.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Sample Container", {"container_label": "TEST-CONT"}):
		c = frappe.new_doc("LIMS Sample Container")
		c.container_type = "TEST-TUBE"
		c.container_label = "TEST-CONT"
		c.barcode = "TEST-CONT-BC"
		c.is_active = 1
		c.insert(ignore_permissions=True)

	for dt, field, name in [
		("LIMS Sample Condition", "condition_name", "TEST-COND"),
		("LIMS Sample Preservation", "preservation_name", "TEST-PRES"),
		("LIMS Sample Matrix", "matrix_name", "TEST-MATRIX"),
	]:
		if not frappe.db.exists(dt, name):
			doc = frappe.new_doc(dt)
			doc.set(field, name)
			doc.code = name
			doc.is_active = 1
			doc.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Storage Location", "TEST-FREEZER"):
		sl = frappe.new_doc("LIMS Storage Location")
		sl.location_name = "TEST-FREEZER"
		sl.is_group = 0
		sl.is_active = 1
		sl.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Instrument Type", "TEST-IT"):
		it = frappe.new_doc("LIMS Instrument Type")
		it.instrument_type_name = "TEST-IT"
		it.code = "TEST-IT"
		it.is_active = 1
		it.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Instrument Location", "TEST-LAB"):
		il = frappe.new_doc("LIMS Instrument Location")
		il.location_name = "TEST-LAB"
		il.is_active = 1
		il.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Attachment Type", "TEST-ATT"):
		at = frappe.new_doc("LIMS Attachment Type")
		at.attachment_type_name = "TEST-ATT"
		at.allowed_for = "Any"
		at.is_active = 1
		at.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Label Template", "TEST-LABEL"):
		lt = frappe.new_doc("LIMS Label Template")
		lt.template_name = "TEST-LABEL"
		lt.label_target = "Sample"
		lt.paper_size = "A4"
		lt.template_html = "<div>Sample: {{ doc.name }}</div>"
		lt.is_active = 1
		lt.is_default = 1
		lt.insert(ignore_permissions=True)

	if not frappe.db.exists("LIMS Analysis Category", "TEST-CAT"):
		cat = frappe.new_doc("LIMS Analysis Category")
		cat.category_name = "TEST-CAT"
		cat.code = "TEST-CAT"
		cat.is_active = 1
		cat.insert(ignore_permissions=True)

	# The profile below links to TEST-HB; create it first to avoid LinkValidationError.
	_get_or_create_analysis_service()

	if not frappe.db.exists("LIMS Analysis Profile", "TEST-PROFILE"):
		p = frappe.new_doc("LIMS Analysis Profile")
		p.profile_name = "TEST-PROFILE"
		p.code = "TEST-PROFILE"
		p.lims_department = "TEST-DEP" if frappe.db.exists("LIMS Department", "TEST-DEP") else None
		p.analysis_category = "TEST-CAT"
		p.is_active = 1
		p.append("items", {"analysis_service": "TEST-HB", "method": "Auto", "unit": "g/dL", "is_active": 1})
		p.insert(ignore_permissions=True)

		if not frappe.db.exists("LIMS Sample Template", "TEST-SAMPLE-TPL"):
			st = frappe.new_doc("LIMS Sample Template")
			st.template_name = "TEST-SAMPLE-TPL"
			st.sample_type = "TEST-ST"
			st.analysis_profile = "TEST-PROFILE"
			st.sample_condition = "TEST-COND"
			st.sample_preservation = "TEST-PRES"
			st.sample_matrix = "TEST-MATRIX"
			container = frappe.db.get_value("LIMS Sample Container", {"container_label": "TEST-CONT"}, "name")
			st.sample_container = container
			st.storage_location = "TEST-FREEZER"
			st.point_of_capture = "lab"
			st.stability_hours = 0
			st.priority = "Normal"
			st.is_active = 1
			st.insert(ignore_permissions=True)


def _create_worksheet(analyst: str | None = None):
	doc = frappe.new_doc("LIMS Worksheet")
	if analyst and frappe.db.exists("User", analyst):
		doc.analyst = analyst
	doc.insert(ignore_permissions=True)
	return doc


def _get_or_create_analysis_service() -> str:
	name = "TEST-HB"
	if not frappe.db.exists("LIMS Analysis Service", name):
		doc = frappe.new_doc("LIMS Analysis Service")
		doc.service_name = name
		doc.service_code = name
		doc.is_numeric_result = 1
		doc.reference_low = 8
		doc.reference_high = 16
		doc.critical_low = 5
		doc.critical_high = 20
		doc.default_method = "Auto"
		doc.unit = "g/dL"
		doc.lims_department = "TEST-DEP" if frappe.db.exists("LIMS Department", "TEST-DEP") else None
		doc.analysis_category = "TEST-CAT" if frappe.db.exists("LIMS Analysis Category", "TEST-CAT") else None
		doc.insert(ignore_permissions=True)
	return name


def _get_or_create_instrument() -> str:
	name = "TEST-ANALYZER"
	if not frappe.db.exists("LIMS Instrument", name):
		doc = frappe.new_doc("LIMS Instrument")
		doc.instrument_name = name
		doc.code = name
		doc.instrument_type = "TEST-IT" if frappe.db.exists("LIMS Instrument Type", "TEST-IT") else None
		doc.instrument_location = "TEST-LAB" if frappe.db.exists("LIMS Instrument Location", "TEST-LAB") else None
		doc.status = "Active"
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
	return name


def _get_or_create_patient() -> str | None:
	if frappe.db.exists("DocType", "Patient"):
		existing = frappe.get_all("Patient", pluck="name", limit=1)
		if existing:
			return existing[0]
		meta = frappe.get_meta("Patient")
		doc = frappe.new_doc("Patient")
		if meta.has_field("patient_name"):
			doc.patient_name = f"TEST-PAT-{frappe.generate_hash(length=6)}"
		if meta.has_field("first_name"):
			doc.first_name = "Test"
		if meta.has_field("last_name"):
			doc.last_name = "Patient"
		if meta.has_field("sex"):
			doc.sex = "Male"
		if meta.has_field("dob"):
			doc.dob = "1990-01-01"
		doc.insert(ignore_permissions=True)
		return doc.name
	return None


def _get_or_create_interpretation_template(analysis_service: str) -> str:
	name = "TEST-CRITICAL-HIGH"
	if not frappe.db.exists("LIMS Interpretation Template", name):
		doc = frappe.new_doc("LIMS Interpretation Template")
		doc.template_name = name
		doc.analysis_service = analysis_service
		doc.priority = 1
		doc.condition_type = "Critical High"
		doc.template_text = "Critical high value detected. Notify clinician immediately."
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
	return name


def _create_sample(sample_type: str, analysis_service: str, patient: str | None):
	doc = frappe.new_doc("LIMS Sample")
	doc.naming_series = "LIMS-SMP-.YYYY.-"
	doc.sample_status = "Received"
	doc.sample_type = sample_type
	doc.sample_template = "TEST-SAMPLE-TPL" if frappe.db.exists("LIMS Sample Template", "TEST-SAMPLE-TPL") else None
	doc.analysis_profile = "TEST-PROFILE" if frappe.db.exists("LIMS Analysis Profile", "TEST-PROFILE") else None
	doc.specimen_status = "Accessioned"
	if frappe.db.exists("LIMS Sample Condition", "TEST-COND"):
		doc.sample_condition = "TEST-COND"
	if frappe.db.exists("LIMS Sample Preservation", "TEST-PRES"):
		doc.sample_preservation = "TEST-PRES"
	if frappe.db.exists("LIMS Sample Matrix", "TEST-MATRIX"):
		doc.sample_matrix = "TEST-MATRIX"
	container = frappe.db.get_value("LIMS Sample Container", {"container_label": "TEST-CONT"}, "name")
	if container:
		doc.sample_container = container
	if frappe.db.exists("LIMS Storage Location", "TEST-FREEZER"):
		doc.storage_location = "TEST-FREEZER"
	if patient:
		doc.patient = patient
	doc.collection_datetime = now_datetime()
	# Workflow expects assignment to happen via worksheet.
	doc.append("analysis_items", {"analysis_service": analysis_service, "result_status": "Unassigned"})
	doc.insert(ignore_permissions=True)
	doc.sample_barcode = doc.name
	doc.save(ignore_permissions=True)
	return doc


def _first_row(sample_doc):
	return sample_doc.analysis_items[0]


def _create_iqc_run(
	instrument: str,
	analysis_service: str,
	measured: float,
	target: float,
	sd: float,
	run_on=None,
):
	doc = frappe.new_doc("LIMS IQC Run")
	doc.naming_series = "IQC-.YYYY.-"
	doc.instrument = instrument
	doc.analysis_service = analysis_service
	doc.control_level = "L1"
	doc.run_on = run_on or now_datetime()
	doc.measured_value = measured
	doc.target_value = target
	doc.sd_value = sd
	doc.insert(ignore_permissions=True)
	return doc


def _create_eqa_plan(analysis_service: str, instrument: str) -> str:
	doc = frappe.new_doc("LIMS EQA Plan")
	doc.plan_title = "TEST-EQA-PLAN"
	doc.program_code = "TEST-PROG"
	doc.provider = "Internal"
	doc.analysis_service = analysis_service
	doc.instrument = instrument
	doc.target_value = 10
	doc.target_sd = 2
	doc.acceptance_z_score = 2
	doc.due_date = now_datetime().date()
	doc.status = "Issued"
	doc.insert(ignore_permissions=True)
	return doc.name


def _create_eqa_result(plan: str, analysis_service: str, sample_doc, instrument: str) -> str:
	doc = frappe.new_doc("LIMS EQA Result")
	doc.eqa_plan = plan
	doc.analysis_service = analysis_service
	doc.instrument = instrument
	doc.sample = sample_doc.name
	doc.reported_value = "11"
	doc.insert(ignore_permissions=True)
	return doc.name


def _create_hl7_message(instrument: str, barcode: str, service: str, value: str):
	payload = "\n".join(
		[
			"MSH|^~\\&|ANALYZER|LAB|LIMS|LAB|202602171200||ORU^R01|MSG0001|P|2.3",
			f"OBR|1|{barcode}|{barcode}|{service}",
			f"OBX|1|NM|{service}^TEST||{value}|g/dL|||||F",
		]
	)
	doc = frappe.new_doc("LIMS Instrument Message")
	doc.instrument = instrument
	doc.message_type = "HL7"
	doc.raw_payload = payload
	doc.insert(ignore_permissions=True)
	return doc
