from __future__ import annotations

import frappe
from frappe.utils import getdate, nowdate


def resolve_specification(sample_doc, row) -> frappe._dict | None:
	"""Return the best matching analysis specification for a sample + item row."""
	if not row.analysis_service:
		return None

	today = getdate(nowdate())
	container_type = None
	if getattr(sample_doc, "sample_container", None):
		container_type = frappe.db.get_value("LIMS Sample Container", sample_doc.sample_container, "container_type")

	# Pull candidates: we filter most conditions in SQL and keep the rest in Python.
	candidates = frappe.get_all(
		"LIMS Analysis Specification",
		filters={
			"is_active": 1,
			"analysis_service": row.analysis_service,
		},
		fields=[
			"name",
			"priority",
			"action_on_fail",
			"sample_type",
			"sample_matrix",
			"sample_condition",
			"sample_preservation",
			"container_type",
			"lims_client",
			"customer",
			"sex",
			"age_min_years",
			"age_max_years",
			"effective_from",
			"effective_to",
			"spec_low",
			"spec_high",
			"allowed_values",
		],
		order_by="priority asc, modified desc",
	)
	if not candidates:
		return None

	demographics = _get_patient_demographics(sample_doc)
	sex = demographics.get("sex") or "Unknown"
	age_years = demographics.get("age_years")

	def _match(s) -> bool:
		if s.sample_type and s.sample_type != getattr(sample_doc, "sample_type", None):
			return False
		if s.sample_matrix and s.sample_matrix != getattr(sample_doc, "sample_matrix", None):
			return False
		if s.sample_condition and s.sample_condition != getattr(sample_doc, "sample_condition", None):
			return False
		if s.sample_preservation and s.sample_preservation != getattr(sample_doc, "sample_preservation", None):
			return False
		if s.container_type and s.container_type != container_type:
			return False
		if s.lims_client and s.lims_client != getattr(sample_doc, "lims_client", None):
			return False
		if s.customer and s.customer != getattr(sample_doc, "customer", None):
			return False
		if s.effective_from and getdate(s.effective_from) > today:
			return False
		if s.effective_to and getdate(s.effective_to) < today:
			return False
		# Sex/age matching
		if (s.sex or "Any") != "Any" and (s.sex or "") != sex:
			return False
		has_age_constraint = s.age_min_years is not None or s.age_max_years is not None
		# If a spec defines age constraints but patient age is unknown, do not match.
		if age_years is None and has_age_constraint:
			return False
		if age_years is not None:
			if s.age_min_years is not None and age_years < float(s.age_min_years):
				return False
			if s.age_max_years is not None and age_years > float(s.age_max_years):
				return False
		return True

	for s in candidates:
		s = frappe._dict(s)
		if _match(s):
			return s
	return None


def check_specification(sample_doc, row) -> frappe._dict:
	"""Evaluate row against best matching spec and return status + message."""
	spec = resolve_specification(sample_doc, row)
	if not spec:
		return frappe._dict(status="Not Applicable", spec=None, message=None, spec_range=None)

	allowed = [v.strip() for v in (spec.allowed_values or "").splitlines() if v.strip()]
	if allowed:
		value = (row.result_value or "").strip()
		if value and value in allowed:
			return frappe._dict(status="Pass", spec=spec, message=None, spec_range=", ".join(allowed))
		return frappe._dict(
			status="Fail",
			spec=spec,
			message=f"Value '{value or '-'}' is not in allowed list",
			spec_range=", ".join(allowed),
		)

	# Numeric range check
	value = _to_float(row.result_value)
	low = spec.spec_low
	high = spec.spec_high
	spec_range = _format_range(low, high)
	if value is None:
		return frappe._dict(status="Not Applicable", spec=spec, message=None, spec_range=spec_range)
	if low is not None and value < float(low):
		return frappe._dict(status="Fail", spec=spec, message=f"Result {value:g} is below spec low {float(low):g}", spec_range=spec_range)
	if high is not None and value > float(high):
		return frappe._dict(status="Fail", spec=spec, message=f"Result {value:g} is above spec high {float(high):g}", spec_range=spec_range)
	return frappe._dict(status="Pass", spec=spec, message=None, spec_range=spec_range)


def _format_range(low, high) -> str | None:
	if low is None and high is None:
		return None
	if low is not None and high is not None:
		return f"{float(low):g} - {float(high):g}"
	if low is not None:
		return f">= {float(low):g}"
	return f"<= {float(high):g}"


def _to_float(value):
	if value in (None, "", "None"):
		return None
	try:
		return float(value)
	except Exception:
		return None


def _get_patient_demographics(sample_doc):
	if not getattr(sample_doc, "patient", None) or not frappe.db.exists("Patient", sample_doc.patient):
		return {"sex": "Unknown", "age_years": None}

	meta = frappe.get_meta("Patient")
	fields = []
	if meta.has_field("sex"):
		fields.append("sex")
	if meta.has_field("dob"):
		fields.append("dob")
	values = frappe.db.get_value("Patient", sample_doc.patient, fields, as_dict=True) if fields else {}

	sex_raw = (values.get("sex") or "").strip().lower() if values else ""
	if sex_raw in {"m", "male"}:
		sex = "Male"
	elif sex_raw in {"f", "female"}:
		sex = "Female"
	else:
		sex = "Unknown"

	age_years = None
	dob = values.get("dob") if values else None
	if dob:
		try:
			days = (getdate(nowdate()) - getdate(dob)).days
			age_years = round(days / 365.25, 2)
		except Exception:
			age_years = None
	return {"sex": sex, "age_years": age_years}
