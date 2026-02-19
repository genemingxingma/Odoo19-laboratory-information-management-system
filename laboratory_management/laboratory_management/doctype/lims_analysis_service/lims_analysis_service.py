import frappe
from frappe.model.document import Document


class LIMSAnalysisService(Document):
	def validate(self):
		self.service_code = (self.service_code or "").strip().upper()
		if not self.service_code:
			frappe.throw("Service Code is required")
		self._validate_ranges()
		self._validate_reference_rules()

	def _validate_ranges(self):
		if self.reference_low is not None and self.reference_high is not None and self.reference_low > self.reference_high:
			frappe.throw("Reference Low cannot be greater than Reference High")
		if self.critical_low is not None and self.critical_high is not None and self.critical_low > self.critical_high:
			frappe.throw("Critical Low cannot be greater than Critical High")
		if self.reference_low is not None and self.critical_low is not None and self.critical_low > self.reference_low:
			frappe.msgprint("Critical Low is usually less than or equal to Reference Low")
		if self.reference_high is not None and self.critical_high is not None and self.critical_high < self.reference_high:
			frappe.msgprint("Critical High is usually greater than or equal to Reference High")

	def _validate_reference_rules(self):
		for rule in self.reference_rules or []:
			if (
				rule.age_min_years is not None
				and rule.age_max_years is not None
				and rule.age_min_years > rule.age_max_years
			):
				frappe.throw(f"Row {rule.idx}: Age Min cannot be greater than Age Max")
			if (
				rule.reference_low is not None
				and rule.reference_high is not None
				and rule.reference_low > rule.reference_high
			):
				frappe.throw(f"Row {rule.idx}: Reference Low cannot be greater than Reference High")
			if (
				rule.critical_low is not None
				and rule.critical_high is not None
				and rule.critical_low > rule.critical_high
			):
				frappe.throw(f"Row {rule.idx}: Critical Low cannot be greater than Critical High")
