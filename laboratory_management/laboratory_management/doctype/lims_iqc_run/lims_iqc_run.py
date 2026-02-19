from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class LIMSIQCRun(Document):
	def validate(self):
		if not self.run_on:
			self.run_on = now_datetime()
		if flt(self.sd_value) <= 0:
			frappe.throw("SD must be greater than 0")
		self.z_score = (flt(self.measured_value) - flt(self.target_value)) / flt(self.sd_value)
		rule, status, message = _evaluate_westgard(self)
		self.westgard_rule = rule
		self.qc_status = status
		self.message = message


@frappe.whitelist()
def review_iqc_run(name: str):
	doc = frappe.get_doc("LIMS IQC Run", name)
	doc.reviewed_by = frappe.session.user
	doc.reviewed_on = now_datetime()
	doc.save(ignore_permissions=True)
	return {"reviewed_by": doc.reviewed_by, "reviewed_on": doc.reviewed_on}


def _evaluate_westgard(doc: LIMSIQCRun):
	z = flt(doc.z_score)
	if abs(z) >= 3:
		return "1_3s", "Fail", "Westgard 1_3s violated"
	if abs(z) >= 2:
		return "1_2s", "Warning", "Westgard 1_2s warning"

	history = frappe.get_all(
		"LIMS IQC Run",
		filters={"instrument": doc.instrument, "analysis_service": doc.analysis_service, "name": ["!=", doc.name]},
		fields=["z_score", "run_on"],
		order_by="run_on desc",
		limit=9,
	)
	zs = [flt(h.z_score) for h in history if h.z_score is not None]
	if len(zs) >= 1 and abs(z) >= 2 and abs(zs[0]) >= 2 and ((z > 0 and zs[0] > 0) or (z < 0 and zs[0] < 0)):
		return "2_2s", "Fail", "Westgard 2_2s violated"
	if len(zs) >= 1 and ((z - zs[0]) >= 4 or (zs[0] - z) >= 4):
		return "R_4s", "Fail", "Westgard R_4s violated"
	if len(zs) >= 3:
		last4 = [z] + zs[:3]
		if all(v >= 1 for v in last4) or all(v <= -1 for v in last4):
			return "4_1s", "Fail", "Westgard 4_1s violated"
	if len(zs) >= 9:
		last10 = [z] + zs[:9]
		if all(v > 0 for v in last10) or all(v < 0 for v in last10):
			return "10x", "Fail", "Westgard 10x violated"
	return "", "Pass", "QC in control"
