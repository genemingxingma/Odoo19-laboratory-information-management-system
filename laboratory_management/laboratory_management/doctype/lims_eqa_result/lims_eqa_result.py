from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from laboratory_management.utils import log_audit


class LIMSEQAResult(Document):
	def validate(self):
		self._compute_evaluation()

	def _compute_evaluation(self):
		self.score_percent = None
		self.z_score = None
		self.evaluation = "Warning"
		if not self.eqa_plan:
			return
		plan = frappe.get_doc("LIMS EQA Plan", self.eqa_plan)
		if not self.analysis_service:
			self.analysis_service = plan.analysis_service

		target = flt(plan.target_value)
		target_sd = flt(plan.target_sd)
		value = _to_float(self.reported_value)
		if value is None:
			return

		if target:
			self.score_percent = max(0, 100 - abs((value - target) / target * 100))
		if target_sd > 0:
			self.z_score = (value - target) / target_sd
			if abs(self.z_score) <= flt(plan.acceptance_z_score or 2):
				self.evaluation = "Pass"
			elif abs(self.z_score) <= flt(plan.acceptance_z_score or 2) * 1.5:
				self.evaluation = "Warning"
			else:
				self.evaluation = "Fail"
		else:
			self.evaluation = "Pass" if self.score_percent is not None and self.score_percent >= 80 else "Warning"

		self.evaluated_on = now_datetime()
		self.evaluated_by = frappe.session.user

	def on_update(self):
		self._ensure_capa_if_needed()
		log_audit(
			"evaluate_eqa_result",
			"LIMS EQA Result",
			self.name,
			{"plan": self.eqa_plan, "evaluation": self.evaluation, "z_score": self.z_score},
		)

	def _ensure_capa_if_needed(self):
		# Avoid CAPA spam: only create when setting enabled, evaluation is Fail,
		# and no CAPA is linked yet.
		if self.evaluation != "Fail" or self.capa:
			return
		if not frappe.db.exists("DocType", "LIMS Settings"):
			return
		settings = frappe.get_cached_doc("LIMS Settings")
		if not int(getattr(settings, "auto_create_capa_on_eqa_fail", 1) or 0):
			return

		doc = frappe.new_doc("LIMS CAPA")
		doc.issue_title = f"EQA Fail: {self.eqa_plan} / {self.analysis_service}"
		doc.source_type = "EQA"
		doc.source_doctype = "LIMS EQA Result"
		doc.source_name = self.name
		doc.sample = self.sample
		doc.analysis_service = self.analysis_service
		doc.owner_user = getattr(settings, "alert_owner", None) or "Administrator"
		doc.issue_description = (
			f"EQA evaluation failed.\n"
			f"Plan: {self.eqa_plan}\n"
			f"Service: {self.analysis_service}\n"
			f"Reported: {self.reported_value}\n"
			f"Z-Score: {self.z_score}\n"
		)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		self.db_set("capa", doc.name, update_modified=False)
		log_audit("auto_create_capa", "LIMS EQA Result", self.name, {"capa": doc.name})


def _to_float(value):
	if value in (None, "", "None"):
		return None
	try:
		return flt(value)
	except Exception:
		return None
