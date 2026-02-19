from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, getdate, now_datetime, nowdate

from laboratory_management.lims_workflow import recompute_sample_status, update_sample_progress
from laboratory_management.security import ROLE_LIMS_ANALYST, ROLE_LIMS_MANAGER, ROLE_LIMS_SAMPLER, ROLE_LIMS_VERIFIER, ensure_roles
from laboratory_management.utils import log_audit

INITIAL_ITEM_STATUS = {"Draft": "Registered", "Sampled": "Registered", "Received": "Unassigned"}
ALLOWED_SIGNATURE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".pdf"}


class LIMSSample(Document):
	def validate(self):
		self._sync_item_defaults()
		self._sync_stability()
		self._sync_tat_overdue()
		self._sync_finance_status()
		self._validate_signature_file()
		recompute_sample_status(self)
		update_sample_progress(self)

	def _sync_item_defaults(self):
		self.sample_barcode = (self.sample_barcode or self.name or "").strip() or None
		self.specimen_status = self.specimen_status or "Registered"
		if self.lims_client and not self.customer:
			self.customer = frappe.db.get_value("LIMS Client", self.lims_client, "customer")
		for row in self.analysis_items:
			if not row.result_status:
				row.result_status = INITIAL_ITEM_STATUS.get(self.sample_status, "Registered")
			if row.analysis_service:
				service = frappe.db.get_value(
					"LIMS Analysis Service",
					row.analysis_service,
					["default_method", "unit", "is_internal_use", "reference_low", "reference_high"],
					as_dict=True,
				)
				if service:
					row.method = row.method or service.default_method
					row.unit = row.unit or service.unit
					if service.reference_low is not None or service.reference_high is not None:
						row.reference_range = _build_reference_range(service.reference_low, service.reference_high, row.unit)
					if service.is_internal_use:
						row.is_internal_use = 1

	def _get_settings(self):
		settings = frappe.get_cached_doc("LIMS Settings") if frappe.db.exists("DocType", "LIMS Settings") else None
		if not settings:
			return frappe._dict(
				required_verifications=1,
				allow_self_verification=0,
				auto_receive_samples=0,
				auto_verify_samples=0,
				rejection_workflow_enabled=1,
				require_critical_ack_on_publish=1,
				delta_check_enabled=1,
				require_delta_ack_on_publish=0,
				delta_threshold_percent=30,
				delta_alert_owner=None,
				enforce_iqc_before_result=1,
				require_critical_notification_on_publish=1,
				require_report_authorization_on_publish=1,
				enforce_specimen_accession_before_result=1,
				enable_specimen_barcode_check=1,
				auto_create_sales_invoice_on_publish=0,
				auto_submit_sales_invoice=1,
				auto_create_payment_entry_on_invoice=0,
				default_mode_of_payment=None,
			)
		return settings

	def _get_client_finance_defaults(self):
		if not self.lims_client:
			return frappe._dict(payment_terms_template=None, taxes_and_charges_template=None, mode_of_payment=None)
		values = frappe.db.get_value(
			"LIMS Client",
			self.lims_client,
			["payment_terms_template", "taxes_and_charges_template", "mode_of_payment"],
			as_dict=True,
		)
		return frappe._dict(values or {})

	def _validate_signature_file(self):
		if not self.coa_signature_file:
			self.coa_signature_type = None
			return
		signature_type = _detect_signature_type(self.coa_signature_file)
		if not signature_type:
			frappe.throw("COA Signature File must be an image (.png/.jpg/.jpeg/.webp/.svg) or .pdf")
		self.coa_signature_type = signature_type

	def _sync_stability(self):
		if not self.stability_hours or self.stability_hours <= 0:
			self.stability_expires_on = None
			self.is_stability_expired = 0
			return
		baseline = self.collection_datetime or self.received_datetime or now_datetime()
		self.stability_expires_on = add_to_date(baseline, hours=int(self.stability_hours), as_datetime=True)
		self.is_stability_expired = 1 if now_datetime() > self.stability_expires_on else 0

	def ensure_not_stability_expired(self):
		if self.is_stability_expired:
			frappe.throw("Sample stability window has expired")

	def ensure_not_on_hold(self):
		if self.is_on_hold:
			frappe.throw("Sample is on hold")

	def _sync_tat_overdue(self):
		if not self.due_date or self.sample_status in {"Dispatched", "Cancelled"}:
			self.is_tat_overdue = 0
			return
		self.is_tat_overdue = 1 if getdate(self.due_date) < getdate(nowdate()) else 0

	def _sync_finance_status(self):
		if not self.sales_invoice:
			self.billing_status = "Not Billed"
			self.payment_status = None
			self.invoice_grand_total = 0
			self.invoice_outstanding = 0
			self.invoice_paid_amount = 0
			return
		si = frappe.db.get_value(
			"Sales Invoice",
			self.sales_invoice,
			["docstatus", "status", "grand_total", "outstanding_amount"],
			as_dict=True,
		)
		if not si:
			self.billing_status = "Not Billed"
			self.payment_status = None
			self.invoice_grand_total = 0
			self.invoice_outstanding = 0
			self.invoice_paid_amount = 0
			return
		total = flt(si.grand_total)
		outstanding = flt(si.outstanding_amount)
		paid = max(total - outstanding, 0)
		self.invoice_grand_total = total
		self.invoice_outstanding = outstanding
		self.invoice_paid_amount = paid
		self.payment_status = si.status
		if si.docstatus == 2:
			self.billing_status = "Cancelled"
		elif self._has_submitted_credit_note():
			self.billing_status = "Credited"
		elif si.docstatus != 1:
			self.billing_status = "Unpaid"
		elif outstanding <= 0:
			self.billing_status = "Paid"
		elif paid > 0:
			self.billing_status = "Partially Paid"
		else:
			self.billing_status = "Unpaid"

	def _has_submitted_credit_note(self) -> bool:
		if not self.credit_note:
			return False
		docstatus = frappe.db.get_value("Sales Invoice", self.credit_note, "docstatus")
		return int(docstatus or 0) == 1

	@frappe.whitelist()
	def action_load_template(self):
		if not self.ar_template:
			frappe.throw("AR Template is required")
		tpl = frappe.get_doc("LIMS AR Template", self.ar_template)
		self.sample_type = self.sample_type or tpl.sample_type
		self.point_of_capture = tpl.point_of_capture
		self.analysis_items = []
		for row in tpl.items:
			self.append(
				"analysis_items",
				{"analysis_service": row.analysis_service, "method": row.method, "unit": row.unit, "result_status": "Registered"},
			)
		if self._get_settings().auto_receive_samples:
			self.sample_status = "Received"
			self.specimen_status = "Accessioned"
			self.accessioned_on = self.accessioned_on or now_datetime()
		self.save()
		log_audit("load_template", "LIMS Sample", self.name, {"template": self.ar_template, "items": len(self.analysis_items)})
		return len(self.analysis_items)

	@frappe.whitelist()
	def action_load_analysis_profile(self):
		if not self.analysis_profile:
			frappe.throw("Analysis Profile is required")
		profile = frappe.get_doc("LIMS Analysis Profile", self.analysis_profile)
		self.analysis_items = []
		for row in profile.items:
			if not int(row.is_active or 0):
				continue
			self.append(
				"analysis_items",
				{
					"analysis_service": row.analysis_service,
					"method": row.method,
					"unit": row.unit,
					"result_status": "Registered",
				},
			)
		if profile.lims_department and not getattr(self, "lims_department", None):
			# Keep future compatibility if sample gets department field later.
			pass
		self.save()
		log_audit("load_analysis_profile", "LIMS Sample", self.name, {"profile": self.analysis_profile, "items": len(self.analysis_items)})
		return len(self.analysis_items)

	@frappe.whitelist()
	def action_load_sample_template(self):
		if not self.sample_template:
			frappe.throw("Sample Template is required")
		tpl = frappe.get_doc("LIMS Sample Template", self.sample_template)
		self.sample_type = self.sample_type or tpl.sample_type
		self.point_of_capture = tpl.point_of_capture or self.point_of_capture
		self.priority = tpl.priority or self.priority
		self.stability_hours = tpl.stability_hours if tpl.stability_hours is not None else self.stability_hours
		# Specimen/master data defaults
		self.sample_condition = self.sample_condition or tpl.sample_condition
		self.sample_preservation = self.sample_preservation or tpl.sample_preservation
		self.sample_matrix = self.sample_matrix or tpl.sample_matrix
		self.sample_container = self.sample_container or tpl.sample_container
		self.storage_location = self.storage_location or tpl.storage_location

		# Services come from analysis profile first, else from template items.
		if tpl.analysis_profile:
			self.analysis_profile = tpl.analysis_profile
			self.action_load_analysis_profile()
			return len(self.analysis_items)

		self.analysis_items = []
		for row in tpl.items:
			if not int(row.is_active or 0):
				continue
			self.append(
				"analysis_items",
				{
					"analysis_service": row.analysis_service,
					"method": row.method,
					"unit": row.unit,
					"result_status": "Registered",
				},
			)
		if self._get_settings().auto_receive_samples:
			self.sample_status = "Received"
			self.specimen_status = "Accessioned"
			self.accessioned_on = self.accessioned_on or now_datetime()
		self.save()
		log_audit("load_sample_template", "LIMS Sample", self.name, {"template": self.sample_template, "items": len(self.analysis_items)})
		return len(self.analysis_items)

	@frappe.whitelist()
	def action_mark_sampled(self):
		ensure_roles(ROLE_LIMS_SAMPLER)
		if self.sample_status not in {"Draft", "Received"}:
			frappe.throw("Only Draft or Received samples can be sampled")
		self.sample_status = "Sampled"
		self.collection_datetime = self.collection_datetime or now_datetime()
		self.collected_on = self.collected_on or self.collection_datetime
		self.specimen_status = "Collected"
		self.sampler = self.sampler or frappe.session.user
		self.save()
		log_audit("mark_sampled", "LIMS Sample", self.name, {"status": self.sample_status})
		return self.sample_status

	@frappe.whitelist()
	def action_receive(self):
		ensure_roles(ROLE_LIMS_SAMPLER)
		self.ensure_not_on_hold()
		if self.sampling_required and not self.collection_datetime:
			frappe.throw("Collection Datetime is required when sampling is enabled")
		if self.sample_status not in {"Draft", "Sampled", "Received"}:
			frappe.throw("Only Draft/Sampled samples can be received")
		self.sample_status = "Received"
		self.received_datetime = self.received_datetime or now_datetime()
		self.specimen_status = "Accessioned"
		self.accessioned_on = self.accessioned_on or self.received_datetime
		for row in self.analysis_items:
			if row.result_status == "Registered":
				row.result_status = "Unassigned"
		self.save()
		log_audit("receive_sample", "LIMS Sample", self.name, {"status": self.sample_status})
		return self.sample_status

	@frappe.whitelist()
	def action_submit_results(self):
		ensure_roles(ROLE_LIMS_ANALYST)
		self.ensure_not_on_hold()
		for row in self.analysis_items:
			if row.result_status in {"Assigned", "Unassigned", "Registered"}:
				frappe.throw(f"Analysis {row.analysis_service} is not submitted")
		self.sample_status = "To Verify"
		self.save()
		log_audit("submit_results", "LIMS Sample", self.name, {"status": self.sample_status})
		return self.sample_status

	@frappe.whitelist()
	def action_verify(self):
		ensure_roles(ROLE_LIMS_VERIFIER)
		self.ensure_not_on_hold()
		for row in self.analysis_items:
			if row.result_status in {"Assigned", "Unassigned", "Registered", "Submitted"}:
				frappe.throw(f"Analysis {row.analysis_service} is not verified")
		self.sample_status = "Verified"
		self.save()
		log_audit("verify_sample", "LIMS Sample", self.name, {"status": self.sample_status})
		return self.sample_status

	@frappe.whitelist()
	def action_publish(self):
		ensure_roles(ROLE_LIMS_VERIFIER)
		self.ensure_not_on_hold()
		if self.sample_status != "Verified":
			frappe.throw("Only verified samples can be published")
		settings = self._get_settings()
		if int(settings.require_critical_ack_on_publish or 0):
			pending = [
				row.analysis_service
				for row in self.analysis_items
				if row.result_status == "Verified" and int(row.is_critical or 0) and not int(row.critical_acknowledged or 0)
			]
			if pending:
				frappe.throw(f"Critical results must be acknowledged before publish: {', '.join(pending)}")
		if int(settings.require_delta_ack_on_publish or 0):
			pending_delta = [
				row.analysis_service
				for row in self.analysis_items
				if row.result_status == "Verified" and int(row.is_delta_alert or 0) and not int(row.delta_acknowledged or 0)
			]
			if pending_delta:
				frappe.throw(f"Delta alerts must be acknowledged before publish: {', '.join(pending_delta)}")
		if int(settings.require_critical_notification_on_publish or 0):
			pending_notify = [
				row.name
				for row in self.analysis_items
				if row.result_status == "Verified" and int(row.is_critical or 0) and not _has_completed_critical_notification(self.name, row.name)
			]
			if pending_notify:
				frappe.throw(f"Critical notification/readback is required before publish: {', '.join(pending_notify)}")
		if int(settings.require_report_authorization_on_publish or 0) and not int(self.is_report_authorized or 0):
			frappe.throw("Report authorization is required before publish")
		self.action_generate_interpretation(save=False)
		self.sample_status = "Published"
		self.published_on = now_datetime()
		self.save()
		log_audit("publish_sample", "LIMS Sample", self.name, {"status": self.sample_status})
		if settings.auto_create_sales_invoice_on_publish:
			self.action_create_sales_invoice(submit_invoice=int(settings.auto_submit_sales_invoice or 0))
			if settings.auto_create_payment_entry_on_invoice:
				self.action_create_payment_entry(submit_payment=1, mode_of_payment=settings.default_mode_of_payment)
		return self.sample_status

	@frappe.whitelist()
	def action_dispatch(self):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		for row in self.analysis_items:
			if row.result_status == "Assigned":
				frappe.throw("Cannot dispatch while analyses are assigned to worksheet")
		if self.sample_status not in {"Published", "Verified"}:
			frappe.throw("Sample must be verified/published before dispatch")
		self.sample_status = "Dispatched"
		self.dispatched_on = now_datetime()
		self.save()
		log_audit("dispatch_sample", "LIMS Sample", self.name, {"status": self.sample_status})
		return self.sample_status

	@frappe.whitelist()
	def action_publish_with_coa(self):
		self.action_publish()
		self.coa_file = frappe.attach_print("LIMS Sample", self.name, file_name=f"COA-{self.name}", print_format="LIMS COA")
		self.save()
		log_audit("publish_coa", "LIMS Sample", self.name, {"coa_file": self.coa_file})
		return {"status": self.sample_status, "coa_file": self.coa_file}

	@frappe.whitelist()
	def action_sign_coa(self, signature_file: str):
		ensure_roles(ROLE_LIMS_VERIFIER)
		if self.sample_status not in {"Published", "Dispatched"}:
			frappe.throw("COA can be signed only after publish")
		signature_type = _detect_signature_type(signature_file)
		if not signature_type:
			frappe.throw("Signature file must be an image or PDF")
		self.coa_signature_file = signature_file
		self.coa_signature_type = signature_type
		self.coa_signed_by = frappe.session.user
		self.coa_signed_on = now_datetime()
		self.save()
		log_audit("sign_coa", "LIMS Sample", self.name, {"signature_type": self.coa_signature_type})
		return {"coa_signature_file": self.coa_signature_file, "coa_signature_type": self.coa_signature_type}

	@frappe.whitelist()
	def action_clear_coa_signature(self):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.coa_signature_file = None
		self.coa_signature_type = None
		self.coa_signed_by = None
		self.coa_signed_on = None
		self.save()
		log_audit("clear_coa_signature", "LIMS Sample", self.name)
		return "cleared"

	@frappe.whitelist()
	def action_create_partition(self, reason: str | None = None):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		if self.is_partition:
			frappe.throw("Partition sample cannot be partitioned again")
		partition = frappe.new_doc("LIMS Sample")
		partition.sample_status = self.sample_status
		partition.lims_client = self.lims_client
		partition.customer = self.customer
		partition.patient = self.patient
		partition.sample_point = self.sample_point
		partition.batch = self.batch
		partition.sample_type = self.sample_type
		partition.priority = self.priority
		partition.point_of_capture = self.point_of_capture
		partition.collection_datetime = self.collection_datetime
		partition.received_datetime = self.received_datetime
		partition.due_date = self.due_date
		partition.parent_sample = self.name
		partition.is_partition = 1
		partition.partition_reason = reason

		for row in self.analysis_items:
			partition.append("analysis_items", {
				"analysis_service": row.analysis_service,
				"method": row.method,
				"unit": row.unit,
				"result_status": row.result_status,
				"is_internal_use": row.is_internal_use,
			})

		partition.insert(ignore_permissions=True)
		log_audit("create_partition", "LIMS Sample", self.name, {"partition": partition.name, "reason": reason})
		return partition.name

	@frappe.whitelist()
	def action_create_sales_order(self, submit_order: int = 1):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		if self.sales_order:
			return self.sales_order
		if not self.customer:
			frappe.throw("Customer is required")
		company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
		doc = frappe.new_doc("Sales Order")
		doc.customer = self.customer
		doc.company = company
		doc.transaction_date = nowdate()
		doc.delivery_date = self.due_date or nowdate()
		finance_defaults = self._get_client_finance_defaults()
		if finance_defaults.payment_terms_template and hasattr(doc, "payment_terms_template"):
			doc.payment_terms_template = finance_defaults.payment_terms_template
		if finance_defaults.taxes_and_charges_template and hasattr(doc, "taxes_and_charges"):
			doc.taxes_and_charges = finance_defaults.taxes_and_charges_template
		for item in self._resolve_billable_items():
			doc.append("items", item)
		doc.insert(ignore_permissions=True)
		if int(submit_order):
			doc.submit()
		self.sales_order = doc.name
		self.save(ignore_permissions=True)
		log_audit("create_sales_order", "LIMS Sample", self.name, {"sales_order": doc.name})
		return doc.name

	@frappe.whitelist()
	def action_create_sales_invoice(self, submit_invoice: int = 1):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		if self.sales_invoice:
			self.action_sync_finance_status()
			return self.sales_invoice
		if self.sales_order:
			from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
			doc = frappe.get_doc(make_sales_invoice(self.sales_order))
		else:
			if not self.customer:
				frappe.throw("Customer is required")
			company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
			doc = frappe.new_doc("Sales Invoice")
			doc.customer = self.customer
			doc.company = company
			doc.posting_date = nowdate()
			doc.due_date = self.due_date or nowdate()
			finance_defaults = self._get_client_finance_defaults()
			if finance_defaults.payment_terms_template and hasattr(doc, "payment_terms_template"):
				doc.payment_terms_template = finance_defaults.payment_terms_template
			if finance_defaults.taxes_and_charges_template and hasattr(doc, "taxes_and_charges"):
				doc.taxes_and_charges = finance_defaults.taxes_and_charges_template
			for item in self._resolve_billable_items():
				doc.append("items", item)
		doc.insert(ignore_permissions=True)
		if int(submit_invoice):
			doc.submit()
		self.sales_invoice = doc.name
		self.action_sync_finance_status(save=False)
		self.save(ignore_permissions=True)
		log_audit("create_sales_invoice", "LIMS Sample", self.name, {"sales_invoice": doc.name})
		return doc.name

	@frappe.whitelist()
	def action_create_payment_entry(self, submit_payment: int = 1, mode_of_payment: str | None = None):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		if not self.sales_invoice:
			frappe.throw("Sales Invoice is required")
		si = frappe.get_doc("Sales Invoice", self.sales_invoice)
		if si.docstatus != 1:
			frappe.throw("Sales Invoice must be submitted before payment entry")
		if flt(si.outstanding_amount) <= 0:
			self.action_sync_finance_status(save=True)
			return self.payment_entry

		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		pe = get_payment_entry("Sales Invoice", si.name)
		payment = frappe.get_doc(pe)
		finance_defaults = self._get_client_finance_defaults()
		payment.mode_of_payment = (
			mode_of_payment
			or finance_defaults.mode_of_payment
			or self._get_settings().default_mode_of_payment
			or payment.mode_of_payment
		)
		payment.insert(ignore_permissions=True)
		if int(submit_payment):
			payment.submit()
		self.payment_entry = payment.name
		self.action_sync_finance_status(save=False)
		self.save(ignore_permissions=True)
		log_audit("create_payment_entry", "LIMS Sample", self.name, {"sales_invoice": si.name, "payment_entry": payment.name})
		return payment.name

	@frappe.whitelist()
	def action_create_credit_note(self, submit_credit_note: int = 1):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.ensure_not_on_hold()
		if not self.sales_invoice:
			frappe.throw("Sales Invoice is required")
		si = frappe.get_doc("Sales Invoice", self.sales_invoice)
		if si.docstatus != 1:
			frappe.throw("Sales Invoice must be submitted before credit note")
		if self.credit_note and frappe.db.exists("Sales Invoice", self.credit_note):
			return self.credit_note

		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
		credit_note = frappe.get_doc(make_sales_return(si.name))
		credit_note.insert(ignore_permissions=True)
		if int(submit_credit_note):
			credit_note.submit()
		self.credit_note = credit_note.name
		self.action_sync_finance_status(save=False)
		self.save(ignore_permissions=True)
		log_audit("create_credit_note", "LIMS Sample", self.name, {"sales_invoice": si.name, "credit_note": credit_note.name})
		return credit_note.name

	@frappe.whitelist()
	def action_sync_finance_status(self, save: bool = True):
		self._sync_finance_status()
		if save:
			self.save(ignore_permissions=True)
		log_audit(
			"sync_finance_status",
			"LIMS Sample",
			self.name,
			{
				"billing_status": self.billing_status,
				"invoice": self.sales_invoice,
				"outstanding": self.invoice_outstanding,
			},
		)
		return {
			"billing_status": self.billing_status,
			"payment_status": self.payment_status,
			"invoice_grand_total": self.invoice_grand_total,
			"invoice_outstanding": self.invoice_outstanding,
			"invoice_paid_amount": self.invoice_paid_amount,
		}

	def _resolve_billable_items(self):
		items = []
		for row in self.analysis_items:
			service = frappe.db.get_value(
				"LIMS Analysis Service", row.analysis_service, ["item_code", "default_price", "service_name"], as_dict=True
			)
			if not service or not service.item_code:
				frappe.throw(f"Billing Item is required for service: {row.analysis_service}")
			items.append({
				"item_code": service.item_code,
				"qty": 1,
				"rate": service.default_price or 0,
				"description": f"{service.service_name} ({self.name})",
			})
		return items

	@frappe.whitelist()
	def action_hold(self, reason: str | None = None):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.is_on_hold = 1
		self.hold_reason = reason
		self.save()
		log_audit("hold_sample", "LIMS Sample", self.name, {"reason": reason})
		return self.is_on_hold

	@frappe.whitelist()
	def action_release_hold(self):
		ensure_roles(ROLE_LIMS_MANAGER)
		self.is_on_hold = 0
		self.hold_reason = None
		self.save()
		log_audit("release_sample_hold", "LIMS Sample", self.name)
		return self.is_on_hold

	@frappe.whitelist()
	def action_generate_interpretation(self, save: bool = True):
		ensure_roles(ROLE_LIMS_VERIFIER)
		lines = []
		for row in self.analysis_items:
			if row.result_status not in {"Submitted", "Verified"}:
				continue
			text = _resolve_interpretation_text(row)
			if text:
				lines.append(f"{row.analysis_service}: {text}")
		if not lines:
			self.preliminary_conclusion = None
			self.final_conclusion = self.final_conclusion or None
		else:
			self.preliminary_conclusion = "\n".join(lines)
			if not self.final_conclusion:
				self.final_conclusion = self.preliminary_conclusion
		if save:
			self.save(ignore_permissions=True)
		log_audit("generate_interpretation", "LIMS Sample", self.name, {"lines": len(lines)})
		return self.preliminary_conclusion

	@frappe.whitelist()
	def action_register_specimen_event(self, event_type: str, location: str | None = None, remarks: str | None = None):
		ensure_roles(ROLE_LIMS_SAMPLER, ROLE_LIMS_ANALYST, ROLE_LIMS_MANAGER)
		doc = frappe.new_doc("LIMS Specimen Event")
		doc.sample = self.name
		doc.barcode = self.sample_barcode or self.name
		doc.event_type = event_type
		doc.location = location
		doc.remarks = remarks
		doc.insert(ignore_permissions=True)
		self.reload()
		return doc.name

	@frappe.whitelist()
	def action_authorize_report(self, final_conclusion: str | None = None):
		ensure_roles(ROLE_LIMS_VERIFIER)
		if self.sample_status not in {"Verified", "Published"}:
			frappe.throw("Sample must be verified before report authorization")
		if final_conclusion:
			self.final_conclusion = final_conclusion
		elif not self.final_conclusion:
			self.action_generate_interpretation(save=False)
		self.is_report_authorized = 1
		self.report_authorized_by = frappe.session.user
		self.report_authorized_on = now_datetime()
		self.save(ignore_permissions=True)
		log_audit("authorize_report", "LIMS Sample", self.name, {"authorized_by": self.report_authorized_by})
		return {"is_report_authorized": self.is_report_authorized, "report_authorized_on": self.report_authorized_on}

	@frappe.whitelist()
	def action_log_critical_notification(
		self,
		sample_item_row: str,
		notified_to: str,
		notification_channel: str | None = "Phone",
		readback_confirmed_by: str | None = None,
		remarks: str | None = None,
	):
		ensure_roles(ROLE_LIMS_VERIFIER)
		row = next((d for d in self.analysis_items if d.name == sample_item_row), None)
		if not row:
			frappe.throw("Sample item not found")
		if not int(row.is_critical or 0):
			frappe.throw("Selected sample item is not a critical result")
		doc = frappe.new_doc("LIMS Critical Notification")
		doc.sample = self.name
		doc.sample_item_row = row.name
		doc.analysis_service = row.analysis_service
		doc.patient = self.patient
		doc.result_value = row.result_value
		doc.critical_flag = row.critical_flag
		doc.notified_to = notified_to
		doc.notification_channel = notification_channel or "Phone"
		doc.notified_on = now_datetime()
		doc.readback_confirmed_by = readback_confirmed_by
		doc.remarks = remarks
		doc.insert(ignore_permissions=True)
		log_audit("log_critical_notification", "LIMS Sample", self.name, {"sample_item_row": row.name, "notification": doc.name})
		return doc.name


def _detect_signature_type(file_url: str | None) -> str | None:
	if not file_url:
		return None
	path = (file_url or "").strip().split("?", 1)[0].lower()
	for ext in ALLOWED_SIGNATURE_EXTENSIONS:
		if path.endswith(ext):
			return "PDF" if ext == ".pdf" else "Image"
	return None


def _build_reference_range(reference_low, reference_high, unit: str | None) -> str | None:
	low = _nullable_float(reference_low)
	high = _nullable_float(reference_high)
	if low is None and high is None:
		return None
	unit_text = unit or ""
	if low is not None and high is not None:
		return f"{low:g} - {high:g} {unit_text}".strip()
	if low is not None:
		return f">= {low:g} {unit_text}".strip()
	return f"<= {high:g} {unit_text}".strip()


def _nullable_float(value):
	if value in (None, "", "None"):
		return None
	return flt(value)


def _resolve_interpretation_text(row) -> str | None:
	condition = _row_condition(row)
	templates = frappe.get_all(
		"LIMS Interpretation Template",
		filters={"analysis_service": row.analysis_service, "is_active": 1},
		fields=["condition_type", "template_text", "priority"],
		order_by="priority asc, modified desc",
	)
	for tpl in templates:
		if tpl.condition_type in {"Any", condition}:
			return tpl.template_text
	if condition == "Critical High":
		return "Critical high result. Immediate clinical notification required."
	if condition == "Critical Low":
		return "Critical low result. Immediate clinical notification required."
	if condition == "Abnormal High":
		return "Result is above reference range."
	if condition == "Abnormal Low":
		return "Result is below reference range."
	if condition == "Delta Alert":
		return "Significant delta change compared with previous result."
	return None


def _row_condition(row) -> str:
	if int(row.is_critical or 0):
		return "Critical High" if row.critical_flag == "HH" else "Critical Low"
	if int(row.is_delta_alert or 0):
		return "Delta Alert"
	if int(row.is_abnormal or 0):
		return "Abnormal High" if row.abnormal_flag == "H" else "Abnormal Low"
	return "Any"


def _has_completed_critical_notification(sample: str, sample_item_row: str) -> bool:
	return bool(
		frappe.db.exists(
			"LIMS Critical Notification",
			{"sample": sample, "sample_item_row": sample_item_row, "status": "Completed"},
		)
	)
