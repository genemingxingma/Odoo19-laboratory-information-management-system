import frappe
from frappe.model.document import Document


class LIMSSettings(Document):
	def validate(self):
		if (self.required_verifications or 1) < 1:
			frappe.throw("Required Verifications must be at least 1")
		if (self.calibration_alert_days or 0) < 0:
			frappe.throw("Calibration Alert Days cannot be negative")
		if (self.tat_alert_days or 0) < 0:
			frappe.throw("TAT Alert Days cannot be negative")
		if (self.eqa_alert_days or 0) < 0:
			frappe.throw("EQA Alert Days cannot be negative")
		if (self.delta_threshold_percent or 0) < 0:
			frappe.throw("Delta Threshold Percent cannot be negative")
