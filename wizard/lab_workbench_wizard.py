from odoo import fields, models


class LabWorkbenchWizard(models.TransientModel):
    _name = "lab.workbench.wizard"
    _description = "Lab Workbench"

    pending_receive_count = fields.Integer(readonly=True)
    in_progress_count = fields.Integer(readonly=True)
    to_verify_count = fields.Integer(readonly=True)
    overdue_count = fields.Integer(readonly=True)
    critical_count = fields.Integer(readonly=True)
    submitted_request_count = fields.Integer(readonly=True)
    quoted_request_count = fields.Integer(readonly=True)
    manual_review_overdue_count = fields.Integer(readonly=True)
    ncr_open_count = fields.Integer(readonly=True)
    interface_failed_count = fields.Integer(readonly=True)
    qc_reject_count = fields.Integer(readonly=True)

    def _count_values(self):
        sample_obj = self.env["lab.sample"]
        analysis_obj = self.env["lab.sample.analysis"]
        request_obj = self.env["lab.test.request"]
        ncr_obj = self.env["lab.nonconformance"]
        iface_obj = self.env["lab.interface.job"]
        qc_obj = self.env["lab.qc.run"]
        return {
            "pending_receive_count": sample_obj.search_count([("state", "=", "draft")]),
            "in_progress_count": sample_obj.search_count([("state", "=", "in_progress")]),
            "to_verify_count": sample_obj.search_count([("state", "=", "to_verify")]),
            "overdue_count": sample_obj.search_count([("is_overdue", "=", True)]),
            "critical_count": analysis_obj.search_count([
                ("is_critical", "=", True),
                ("state", "in", ("pending", "assigned", "done")),
            ]),
            "submitted_request_count": request_obj.search_count([("state", "=", "submitted")]),
            "quoted_request_count": request_obj.search_count([("state", "=", "quoted")]),
            "manual_review_overdue_count": analysis_obj.search_count([("review_overdue", "=", True)]),
            "ncr_open_count": ncr_obj.search_count([("state", "in", ("open", "investigation", "capa"))]),
            "interface_failed_count": iface_obj.search_count([("state", "in", ("failed", "dead_letter"))]),
            "qc_reject_count": qc_obj.search_count([("status", "=", "reject")]),
        }

    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        vals = self._count_values()
        res.update({k: vals[k] for k in vals if k in fields_list})
        return res

    def action_open_receive(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Samples to Receive",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("state", "=", "draft")],
        }

    def action_open_in_progress(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Samples In Progress",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("state", "=", "in_progress")],
        }

    def action_open_to_verify(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Samples To Verify",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("state", "=", "to_verify")],
        }

    def action_open_overdue(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Overdue Samples",
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": [("is_overdue", "=", True)],
        }

    def action_open_critical(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Critical Analyses",
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": [
                ("is_critical", "=", True),
                ("state", "in", ("pending", "assigned", "done")),
            ],
        }

    def action_open_submitted_requests(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Submitted Requests",
            "res_model": "lab.test.request",
            "view_mode": "list,form",
            "domain": [("state", "=", "submitted")],
        }

    def action_open_quoted_requests(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Quoted Requests",
            "res_model": "lab.test.request",
            "view_mode": "list,form",
            "domain": [("state", "=", "quoted")],
        }

    def action_open_manual_review_overdue(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Manual Review Overdue",
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": [("review_overdue", "=", True)],
        }

    def action_open_ncr_open(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Open NCR",
            "res_model": "lab.nonconformance",
            "view_mode": "list,form",
            "domain": [("state", "in", ("open", "investigation", "capa"))],
        }

    def action_open_interface_failed(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Failed Interface Jobs",
            "res_model": "lab.interface.job",
            "view_mode": "list,form",
            "domain": [("state", "in", ("failed", "dead_letter"))],
        }

    def action_open_qc_reject(self):
        return {
            "type": "ir.actions.act_window",
            "name": "Rejected QC Runs",
            "res_model": "lab.qc.run",
            "view_mode": "list,form",
            "domain": [("status", "=", "reject")],
        }
