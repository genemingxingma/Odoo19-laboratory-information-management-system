import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate, nowdate

from laboratory_management.utils import log_audit

ASSET_LAST_CALIBRATION = "custom_lims_last_calibration_date"
ASSET_CALIBRATION_CYCLE = "custom_lims_calibration_cycle_days"
ASSET_CALIBRATION_DUE = "custom_lims_calibration_due_date"


class LIMSInstrument(Document):
	def validate(self):
		self.code = (self.code or "").strip().upper()
		if not self.code:
			frappe.throw("Code is required")
		if self.asset:
			self.sync_calibration_from_asset()
		self._normalize_due_date()
		self._compute_overdue()

	def _normalize_due_date(self):
		if self.calibration_due_on:
			return
		if self.last_calibrated_on and self.calibration_cycle_days and int(self.calibration_cycle_days) > 0:
			self.calibration_due_on = add_days(self.last_calibrated_on, int(self.calibration_cycle_days))

	def _compute_overdue(self):
		if self.calibration_due_on:
			self.is_calibration_overdue = 1 if getdate(self.calibration_due_on) < getdate(nowdate()) else 0
		else:
			self.is_calibration_overdue = 0

	def sync_calibration_from_asset(self):
		if not self.asset:
			return
		values = frappe.db.get_value(
			"Asset",
			self.asset,
			[ASSET_LAST_CALIBRATION, ASSET_CALIBRATION_CYCLE, ASSET_CALIBRATION_DUE, "asset_name"],
			as_dict=True,
		)
		if not values:
			frappe.throw(f"Asset {self.asset} not found")
		if values.asset_name and not self.instrument_name:
			self.instrument_name = values.asset_name
		self.last_calibrated_on = values.get(ASSET_LAST_CALIBRATION) or self.last_calibrated_on
		self.calibration_cycle_days = values.get(ASSET_CALIBRATION_CYCLE) or self.calibration_cycle_days
		self.calibration_due_on = values.get(ASSET_CALIBRATION_DUE) or self.calibration_due_on

	@frappe.whitelist()
	def action_sync_from_asset(self):
		self.sync_calibration_from_asset()
		self._normalize_due_date()
		self._compute_overdue()
		self.save()
		log_audit("sync_instrument_from_asset", "LIMS Instrument", self.name, {"asset": self.asset})
		return {
			"last_calibrated_on": self.last_calibrated_on,
			"calibration_cycle_days": self.calibration_cycle_days,
			"calibration_due_on": self.calibration_due_on,
			"is_calibration_overdue": self.is_calibration_overdue,
		}

	@frappe.whitelist()
	def action_push_calibration_to_asset(self):
		if not self.asset:
			frappe.throw("Asset is required")
		asset = frappe.get_doc("Asset", self.asset)
		asset.set(ASSET_LAST_CALIBRATION, self.last_calibrated_on)
		asset.set(ASSET_CALIBRATION_CYCLE, self.calibration_cycle_days)
		asset.set(ASSET_CALIBRATION_DUE, self.calibration_due_on)
		asset.save(ignore_permissions=True)
		log_audit("push_instrument_to_asset", "LIMS Instrument", self.name, {"asset": self.asset})
		return self.asset
