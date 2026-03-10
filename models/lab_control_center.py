from odoo import _, api, fields, models


class LabControlCenterWizard(models.TransientModel):
    _name = "lab.control.center.wizard"
    _description = "Lab Control Center"
    _rec_name = "title"

    title = fields.Char(default=lambda self: _("Control Center"), readonly=True)

    flow_html = fields.Html(compute="_compute_flow_html")
    guide_html = fields.Html(compute="_compute_guide_html")
    alert_html = fields.Html(compute="_compute_alert_html")

    request_draft_count = fields.Integer(compute="_compute_metrics")
    request_triage_count = fields.Integer(compute="_compute_metrics")
    request_quote_count = fields.Integer(compute="_compute_metrics")
    request_approved_count = fields.Integer(compute="_compute_metrics")

    sample_received_count = fields.Integer(compute="_compute_metrics")
    sample_in_progress_count = fields.Integer(compute="_compute_metrics")
    sample_to_verify_count = fields.Integer(compute="_compute_metrics")
    sample_overdue_count = fields.Integer(compute="_compute_metrics")

    analysis_manual_review_count = fields.Integer(compute="_compute_metrics")
    report_unacked_count = fields.Integer(compute="_compute_metrics")
    qc_reject_recent_count = fields.Integer(compute="_compute_metrics")
    task_open_count = fields.Integer(compute="_compute_metrics")
    change_open_count = fields.Integer(compute="_compute_metrics")
    change_ready_count = fields.Integer(compute="_compute_metrics")
    nonconformance_open_count = fields.Integer(compute="_compute_metrics")
    risk_open_count = fields.Integer(compute="_compute_metrics")
    risk_high_count = fields.Integer(compute="_compute_metrics")
    waste_open_count = fields.Integer(compute="_compute_metrics")
    waste_overdue_count = fields.Integer(compute="_compute_metrics")

    @api.model
    def _company_domain(self, model_name):
        model = self.env[model_name]
        if "company_id" in model._fields:
            return [("company_id", "=", self.env.company.id)]
        return []

    def _compute_metrics(self):
        request_obj = self.env["lab.test.request"]
        sample_obj = self.env["lab.sample"]
        analysis_obj = self.env["lab.sample.analysis"]
        dispatch_obj = self.env["lab.report.dispatch"]
        qc_obj = self.env["lab.qc.run"]
        task_obj = self.env["lab.workstation.task"]
        change_obj = self.env["lab.change.control"]
        nc_obj = self.env["lab.nonconformance"]
        risk_obj = self.env["lab.risk.register"]
        waste_obj = self.env["lab.medical.waste.batch"]

        req_company = self._company_domain("lab.test.request")
        sample_company = self._company_domain("lab.sample")
        analysis_company = self._company_domain("lab.sample.analysis")
        dispatch_company = self._company_domain("lab.report.dispatch")
        qc_company = self._company_domain("lab.qc.run")
        task_company = self._company_domain("lab.workstation.task")
        change_company = self._company_domain("lab.change.control")
        nc_company = self._company_domain("lab.nonconformance")
        risk_company = self._company_domain("lab.risk.register")
        waste_company = self._company_domain("lab.medical.waste.batch")

        recent_qc_date = fields.Datetime.subtract(fields.Datetime.now(), days=7)

        for rec in self:
            rec.request_draft_count = request_obj.search_count(req_company + [("state", "=", "draft")])
            rec.request_triage_count = request_obj.search_count(req_company + [("state", "in", ("submitted", "triage"))])
            rec.request_quote_count = request_obj.search_count(req_company + [("state", "=", "quoted")])
            rec.request_approved_count = request_obj.search_count(req_company + [("state", "=", "approved")])

            rec.sample_received_count = sample_obj.search_count(sample_company + [("state", "=", "received")])
            rec.sample_in_progress_count = sample_obj.search_count(sample_company + [("state", "=", "in_progress")])
            rec.sample_to_verify_count = sample_obj.search_count(sample_company + [("state", "=", "to_verify")])
            rec.sample_overdue_count = sample_obj.search_count(sample_company + [("is_overdue", "=", True)])

            rec.analysis_manual_review_count = analysis_obj.search_count(
                analysis_company + [("needs_manual_review", "=", True), ("state", "in", ("assigned", "done"))]
            )
            rec.report_unacked_count = dispatch_obj.search_count(dispatch_company + [("state", "in", ("sent", "viewed", "downloaded"))])
            rec.qc_reject_recent_count = qc_obj.search_count(qc_company + [("run_date", ">=", recent_qc_date), ("status", "=", "reject")])
            rec.task_open_count = task_obj.search_count(task_company + [("state", "in", ("open", "in_progress"))])
            rec.change_open_count = change_obj.search_count(
                change_company + [("state", "in", ("impact", "approval", "approved", "implementation", "validation", "effective"))]
            )
            rec.change_ready_count = change_obj.search_count(
                change_company + [("effective_ready", "=", True), ("state", "in", ("approved", "implementation", "validation"))]
            )
            rec.nonconformance_open_count = nc_obj.search_count(nc_company + [("state", "not in", ("closed", "cancel"))])
            rec.risk_open_count = risk_obj.search_count(risk_company + [("state", "not in", ("closed", "accepted", "cancel"))])
            rec.risk_high_count = risk_obj.search_count(risk_company + [("state", "not in", ("closed", "accepted", "cancel")), ("risk_level", "in", ("high", "critical"))])
            rec.waste_open_count = waste_obj.search_count(waste_company + [("state", "not in", ("disposed", "cancel"))])
            rec.waste_overdue_count = waste_obj.search_count(waste_company + [("is_overdue", "=", True)])

    def _compute_flow_html(self):
        for rec in self:
            rec.flow_html = _(
                """
<div style="border:1px solid #dbe4f0;border-radius:14px;padding:16px;background:linear-gradient(135deg,#f8fbff 0%%,#eef5ff 100%%);">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;">
    <div>
      <div style="font-size:18px;font-weight:700;color:#183153;">Laboratory Control Center</div>
      <div style="font-size:13px;color:#50627c;margin-top:4px;">Use this page as the daily start point: check queue pressure, review compliance blockers, then jump to the correct work area.</div>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;">
      <span style="background:#ffffff;border:1px solid #d3dff2;border-radius:999px;padding:4px 10px;color:#26466d;font-size:12px;">Requests %(requests)s</span>
      <span style="background:#ffffff;border:1px solid #d3dff2;border-radius:999px;padding:4px 10px;color:#26466d;font-size:12px;">Verification %(verify)s</span>
      <span style="background:#ffffff;border:1px solid #d3dff2;border-radius:999px;padding:4px 10px;color:#26466d;font-size:12px;">Compliance %(compliance)s</span>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-top:14px;">
    <div style="background:#fff;border:1px solid #dbe4f0;border-radius:12px;padding:12px;">
      <div style="font-weight:700;color:#183153;">1. Front Desk</div>
      <div style="font-size:12px;color:#5a6d88;margin-top:4px;">Requests waiting for draft cleanup, triage, quote, and approval.</div>
    </div>
    <div style="background:#fff;border:1px solid #dbe4f0;border-radius:12px;padding:12px;">
      <div style="font-weight:700;color:#183153;">2. Testing</div>
      <div style="font-size:12px;color:#5a6d88;margin-top:4px;">Samples, worksheets, runs, manual review, and analyst workload.</div>
    </div>
    <div style="background:#fff;border:1px solid #dbe4f0;border-radius:12px;padding:12px;">
      <div style="font-weight:700;color:#183153;">3. Review &amp; Release</div>
      <div style="font-size:12px;color:#5a6d88;margin-top:4px;">Verification, report dispatch, pending acknowledgements, and overdue items.</div>
    </div>
    <div style="background:#fff;border:1px solid #dbe4f0;border-radius:12px;padding:12px;">
      <div style="font-weight:700;color:#183153;">4. Governance</div>
      <div style="font-size:12px;color:#5a6d88;margin-top:4px;">Change control, CAPA, risk register, and medical waste traceability.</div>
    </div>
  </div>
</div>
"""
            ) % {
                "requests": rec.request_draft_count + rec.request_triage_count + rec.request_quote_count,
                "verify": rec.sample_to_verify_count + rec.analysis_manual_review_count,
                "compliance": rec.change_open_count + rec.nonconformance_open_count + rec.risk_open_count,
            }

    def _compute_guide_html(self):
        for rec in self:
            role_cards = []
            if rec.env.user.has_group("laboratory_management.group_lab_reception"):
                role_cards.append(
                    """
<div style="border:1px solid #d9e5f7;border-radius:10px;padding:10px;background:#fff;">
  <div style="font-weight:700;color:#1f365c;">Reception Focus</div>
  <div style="font-size:12px;color:#4c6280;margin-top:4px;">Start with triage and quote queues, then review submitted requests that still miss specimen or patient completeness.</div>
</div>
"""
                )
            if rec.env.user.has_group("laboratory_management.group_lab_analyst"):
                role_cards.append(
                    """
<div style="border:1px solid #d9e5f7;border-radius:10px;padding:10px;background:#fff;">
  <div style="font-weight:700;color:#1f365c;">Analyst Focus</div>
  <div style="font-size:12px;color:#4c6280;margin-top:4px;">Work from accession queues to worksheets, then clear in-progress and manual review analysis items.</div>
</div>
"""
                )
            if rec.env.user.has_group("laboratory_management.group_lab_reviewer"):
                role_cards.append(
                    """
<div style="border:1px solid #d9e5f7;border-radius:10px;padding:10px;background:#fff;">
  <div style="font-weight:700;color:#1f365c;">Reviewer Focus</div>
  <div style="font-size:12px;color:#4c6280;margin-top:4px;">Prioritize verification queues, manual review backlog, overdue samples, and report dispatch acknowledgements.</div>
</div>
"""
                )
            if rec.env.user.has_group("laboratory_management.group_lab_quality_manager"):
                role_cards.append(
                    """
<div style="border:1px solid #d9e5f7;border-radius:10px;padding:10px;background:#fff;">
  <div style="font-weight:700;color:#1f365c;">Quality Focus</div>
  <div style="font-size:12px;color:#4c6280;margin-top:4px;">Track QC rejects, nonconformance, change control readiness, risk register, and medical waste overdue batches.</div>
</div>
"""
                )
            rec.guide_html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;">%s</div>' % "".join(role_cards or [
                """
<div style="border:1px solid #d9e5f7;border-radius:10px;padding:10px;background:#fff;">
  <div style="font-weight:700;color:#1f365c;">Daily Use</div>
  <div style="font-size:12px;color:#4c6280;margin-top:4px;">Pick the queue that matches your role, clear overdue items first, then move to governance blockers before releasing reports.</div>
</div>
"""
            ])

    def _compute_alert_html(self):
        for rec in self:
            items = []
            if rec.sample_overdue_count:
                items.append(_("Overdue samples: %s") % rec.sample_overdue_count)
            if rec.qc_reject_recent_count:
                items.append(_("QC rejects in last 7 days: %s") % rec.qc_reject_recent_count)
            if rec.risk_high_count:
                items.append(_("High/critical open risks: %s") % rec.risk_high_count)
            if rec.waste_overdue_count:
                items.append(_("Overdue medical waste batches: %s") % rec.waste_overdue_count)
            if rec.change_ready_count:
                items.append(_("Changes ready for effectiveness decision: %s") % rec.change_ready_count)
            if rec.report_unacked_count:
                items.append(_("Reports sent but not acknowledged: %s") % rec.report_unacked_count)
            if not items:
                items.append(_("No critical operational alerts at the moment."))
            rec.alert_html = "<ul style='margin:0;padding-left:18px;color:#39506f;font-size:13px;'>%s</ul>" % "".join(
                "<li>%s</li>" % item for item in items
            )

    @api.model
    def _action(self, xmlid):
        return self.env.ref(xmlid).sudo().read()[0]

    def action_open_new_request(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("New Test Request"),
            "res_model": "lab.test.request",
            "view_mode": "form",
            "target": "current",
            "context": {"default_request_type": "individual"},
        }

    def action_open_requests_all(self):
        return self._action("laboratory_management.action_lab_test_request")

    def action_open_requests_triage(self):
        return self._action("laboratory_management.action_lab_test_request_to_triage")

    def action_open_requests_quote(self):
        return self._action("laboratory_management.action_lab_test_request_to_quote")

    def action_open_samples_all(self):
        return self._action("laboratory_management.action_lab_sample")

    def action_open_analysis_queue(self):
        return self._action("laboratory_management.action_lab_analysis_queue")

    def action_open_samples_to_verify(self):
        return self._action("laboratory_management.action_lab_sample_to_verify")

    def action_open_manual_review(self):
        return self._action("laboratory_management.action_lab_manual_review_queue")

    def action_open_worksheets(self):
        return self._action("laboratory_management.action_lab_worksheet")

    def action_open_dispatch_unacked(self):
        return self._action("laboratory_management.action_lab_report_dispatch_unacked")

    def action_open_qc_runs(self):
        return self._action("laboratory_management.action_lab_qc_run")

    def action_open_task_board(self):
        return self._action("laboratory_management.action_lab_task_board_wizard")

    def action_open_change_control(self):
        return self._action("laboratory_management.action_lab_change_control")

    def action_open_nonconformance(self):
        return self._action("laboratory_management.action_lab_nonconformance")

    def action_open_risk_register(self):
        return self._action("laboratory_management.action_lab_risk_register")

    def action_open_medical_waste(self):
        return self._action("laboratory_management.action_lab_medical_waste_batch")

    def name_get(self):
        return [(rec.id, _("Control Center")) for rec in self]
