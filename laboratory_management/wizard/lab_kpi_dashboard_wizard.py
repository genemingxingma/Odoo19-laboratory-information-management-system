from odoo import _, fields, models


class LabKpiDashboardWizard(models.TransientModel):
    _name = "lab.kpi.dashboard.wizard"
    _description = "Lab KPI Dashboard"

    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.today)

    total_reported_samples = fields.Integer(readonly=True)
    tat_on_time_samples = fields.Integer(readonly=True)
    tat_overdue_samples = fields.Integer(readonly=True)
    tat_rate = fields.Float(readonly=True)

    total_analysis = fields.Integer(readonly=True)
    retest_count = fields.Integer(readonly=True)
    retest_rate = fields.Float(readonly=True)

    total_qc_runs = fields.Integer(readonly=True)
    qc_reject_count = fields.Integer(readonly=True)
    qc_reject_rate = fields.Float(readonly=True)

    def _sample_domain(self):
        return [
            ("report_date", "!=", False),
            ("report_date", ">=", self.date_from),
            ("report_date", "<=", self.date_to),
        ]

    def action_refresh(self):
        self.ensure_one()

        sample_obj = self.env["lab.sample"]
        analysis_obj = self.env["lab.sample.analysis"]
        qc_obj = self.env["lab.qc.run"]

        sample_domain = self._sample_domain()
        samples = sample_obj.search(sample_domain)

        total_reported = len(samples)
        on_time = len(samples.filtered(lambda s: s.expected_report_date and s.report_date <= s.expected_report_date))
        overdue = total_reported - on_time
        tat_rate = (on_time / total_reported * 100.0) if total_reported else 0.0

        analysis_domain = [
            ("sample_id.report_date", "!=", False),
            ("sample_id.report_date", ">=", self.date_from),
            ("sample_id.report_date", "<=", self.date_to),
        ]
        total_analysis = analysis_obj.search_count(analysis_domain)
        retest_count = analysis_obj.search_count(analysis_domain + [("is_retest", "=", True)])
        retest_rate = (retest_count / total_analysis * 100.0) if total_analysis else 0.0

        qc_domain = [
            ("run_date", ">=", self.date_from),
            ("run_date", "<=", self.date_to),
        ]
        total_qc = qc_obj.search_count(qc_domain)
        qc_reject = qc_obj.search_count(qc_domain + [("status", "=", "reject")])
        qc_reject_rate = (qc_reject / total_qc * 100.0) if total_qc else 0.0

        self.write(
            {
                "total_reported_samples": total_reported,
                "tat_on_time_samples": on_time,
                "tat_overdue_samples": overdue,
                "tat_rate": tat_rate,
                "total_analysis": total_analysis,
                "retest_count": retest_count,
                "retest_rate": retest_rate,
                "total_qc_runs": total_qc,
                "qc_reject_count": qc_reject,
                "qc_reject_rate": qc_reject_rate,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "res_model": "lab.kpi.dashboard.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_overdue_samples(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Overdue Samples"),
            "res_model": "lab.sample",
            "view_mode": "list,form",
            "domain": self._sample_domain() + [("is_overdue", "=", True)],
        }

    def action_open_retest_analysis(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retest Analysis"),
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": [
                ("sample_id.report_date", "!=", False),
                ("sample_id.report_date", ">=", self.date_from),
                ("sample_id.report_date", "<=", self.date_to),
                ("is_retest", "=", True),
            ],
        }

    def action_open_qc_reject(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Rejected QC Runs"),
            "res_model": "lab.qc.run",
            "view_mode": "list,form",
            "domain": [
                ("run_date", ">=", self.date_from),
                ("run_date", "<=", self.date_to),
                ("status", "=", "reject"),
            ],
        }
