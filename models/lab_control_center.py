from odoo import _, api, fields, models


class LabControlCenterWizard(models.TransientModel):
    _name = "lab.control.center.wizard"
    _description = "Lab Control Center"

    flow_html = fields.Html(compute="_compute_flow_html")
    guide_html = fields.Html(compute="_compute_guide_html")

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

        req_company = self._company_domain("lab.test.request")
        sample_company = self._company_domain("lab.sample")
        analysis_company = self._company_domain("lab.sample.analysis")
        dispatch_company = self._company_domain("lab.report.dispatch")
        qc_company = self._company_domain("lab.qc.run")
        task_company = self._company_domain("lab.workstation.task")

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

    def _compute_flow_html(self):
        flow_text = _(
            """
<div class="o_lab_cc_flow">
  <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;">
    <div class="badge rounded-pill text-bg-secondary">1) Request</div>
    <div>→</div>
    <div class="badge rounded-pill text-bg-secondary">2) Sample</div>
    <div>→</div>
    <div class="badge rounded-pill text-bg-secondary">3) Analysis</div>
    <div>→</div>
    <div class="badge rounded-pill text-bg-secondary">4) Review</div>
    <div>→</div>
    <div class="badge rounded-pill text-bg-secondary">5) Report</div>
    <div>→</div>
    <div class="badge rounded-pill text-bg-secondary">6) Dispatch / Portal</div>
  </div>
  <p style="margin-top:8px;">Use the buttons below to jump to each queue directly. This page is the recommended single entry point for daily operations.</p>
</div>
"""
        )
        for rec in self:
            rec.flow_html = flow_text

    def _compute_guide_html(self):
        guide = _(
            """
<ul>
  <li><b>Reception</b>: Create request, verify patient/specimen data, start triage/quote.</li>
  <li><b>Analyst</b>: Receive sample, start analysis, complete result entry and mark done.</li>
  <li><b>Reviewer</b>: Process manual review, technical/medical review, and release report.</li>
  <li><b>Quality</b>: Monitor QC rejects, overdue samples, and open tasks for risk control.</li>
</ul>
"""
        )
        for rec in self:
            rec.guide_html = guide

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
