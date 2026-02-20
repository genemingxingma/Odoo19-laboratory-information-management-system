import base64
import csv
from io import StringIO

from odoo import _, fields, models


class LabManualReviewReportWizard(models.TransientModel):
    _name = "lab.manual.review.report.wizard"
    _description = "Manual Review Report Wizard"

    date_from = fields.Date(required=True, default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(required=True, default=fields.Date.today)

    pending_manual_reviews = fields.Integer(readonly=True)
    overdue_manual_reviews = fields.Integer(readonly=True)
    completed_manual_reviews = fields.Integer(readonly=True)
    on_time_completed = fields.Integer(readonly=True)
    on_time_rate = fields.Float(readonly=True)
    avg_review_hours = fields.Float(readonly=True)

    line_ids = fields.One2many("lab.manual.review.report.line", "wizard_id", readonly=True)
    reviewer_line_ids = fields.One2many("lab.manual.review.reviewer.line", "wizard_id", readonly=True)

    def _pending_domain(self):
        self.ensure_one()
        return [
            ("needs_manual_review", "=", True),
            ("state", "in", ("assigned", "done")),
            ("create_date", ">=", self.date_from),
            ("create_date", "<=", self.date_to),
        ]

    def _completed_domain(self):
        self.ensure_one()
        return [
            ("manual_reviewed_date", "!=", False),
            ("manual_reviewed_date", ">=", self.date_from),
            ("manual_reviewed_date", "<=", self.date_to),
        ]

    def action_refresh(self):
        self.ensure_one()
        analysis_obj = self.env["lab.sample.analysis"]

        pending = analysis_obj.search(self._pending_domain())
        overdue = pending.filtered(lambda x: x.review_overdue)
        completed = analysis_obj.search(self._completed_domain())
        on_time = completed.filtered(
            lambda x: (not x.review_due_date) or (x.manual_reviewed_date and x.manual_reviewed_date <= x.review_due_date)
        )

        durations = []
        for line in completed:
            start_dt = line.review_assigned_date or line.create_date
            end_dt = line.manual_reviewed_date
            if start_dt and end_dt and end_dt >= start_dt:
                durations.append((end_dt - start_dt).total_seconds() / 3600.0)

        avg_hours = (sum(durations) / len(durations)) if durations else 0.0
        on_time_rate = (len(on_time) / len(completed) * 100.0) if completed else 0.0

        reason_buckets = {}
        reviewer_buckets = {}
        for line in pending + completed:
            code = line.manual_review_reason_code or "unclassified"
            if code not in reason_buckets:
                reason_buckets[code] = {"pending": 0, "completed": 0}
            if line in pending:
                reason_buckets[code]["pending"] += 1
            if line in completed:
                reason_buckets[code]["completed"] += 1

        for line in completed:
            reviewer = line.manual_reviewed_by_id
            if not reviewer:
                continue
            key = reviewer.id
            if key not in reviewer_buckets:
                reviewer_buckets[key] = {
                    "reviewer_id": reviewer.id,
                    "completed_count": 0,
                    "overdue_completed_count": 0,
                    "durations": [],
                }
            bucket = reviewer_buckets[key]
            bucket["completed_count"] += 1
            if line.review_due_date and line.manual_reviewed_date and line.manual_reviewed_date > line.review_due_date:
                bucket["overdue_completed_count"] += 1
            start_dt = line.review_assigned_date or line.create_date
            end_dt = line.manual_reviewed_date
            if start_dt and end_dt and end_dt >= start_dt:
                bucket["durations"].append((end_dt - start_dt).total_seconds() / 3600.0)

        detail_lines = [(5, 0, 0)]
        for code in sorted(reason_buckets.keys()):
            detail_lines.append(
                (
                    0,
                    0,
                    {
                        "reason_code": code,
                        "pending_count": reason_buckets[code]["pending"],
                        "completed_count": reason_buckets[code]["completed"],
                    },
                )
            )

        reviewer_lines = [(5, 0, 0)]
        for _key, bucket in sorted(
            reviewer_buckets.items(),
            key=lambda item: (-item[1]["completed_count"], item[1]["reviewer_id"]),
        ):
            avg_reviewer_hours = (
                sum(bucket["durations"]) / len(bucket["durations"]) if bucket["durations"] else 0.0
            )
            reviewer_lines.append(
                (
                    0,
                    0,
                    {
                        "reviewer_id": bucket["reviewer_id"],
                        "completed_count": bucket["completed_count"],
                        "overdue_completed_count": bucket["overdue_completed_count"],
                        "avg_review_hours": avg_reviewer_hours,
                    },
                )
            )

        self.write(
            {
                "pending_manual_reviews": len(pending),
                "overdue_manual_reviews": len(overdue),
                "completed_manual_reviews": len(completed),
                "on_time_completed": len(on_time),
                "on_time_rate": on_time_rate,
                "avg_review_hours": avg_hours,
                "line_ids": detail_lines,
                "reviewer_line_ids": reviewer_lines,
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": "lab.manual.review.report.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_open_pending(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pending Manual Reviews"),
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": self._pending_domain(),
        }

    def action_open_overdue(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Overdue Manual Reviews"),
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": self._pending_domain()
            + [
                ("needs_manual_review", "=", True),
                ("review_due_date", "!=", False),
                ("review_due_date", "<", fields.Datetime.now()),
            ],
        }

    def action_open_completed(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Completed Manual Reviews"),
            "res_model": "lab.sample.analysis",
            "view_mode": "list,form",
            "domain": self._completed_domain(),
        }

    def action_export_csv(self):
        self.ensure_one()
        self.action_refresh()

        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Metric", "Value"])
        writer.writerow(["Date From", self.date_from or ""])
        writer.writerow(["Date To", self.date_to or ""])
        writer.writerow(["Pending Manual Reviews", self.pending_manual_reviews])
        writer.writerow(["Overdue Manual Reviews", self.overdue_manual_reviews])
        writer.writerow(["Completed Manual Reviews", self.completed_manual_reviews])
        writer.writerow(["On-time Completed", self.on_time_completed])
        writer.writerow(["On-time Rate (%)", round(self.on_time_rate, 2)])
        writer.writerow(["Avg Review Hours", round(self.avg_review_hours, 2)])
        writer.writerow([])
        writer.writerow(["Reason", "Pending", "Completed"])
        for line in self.line_ids:
            writer.writerow([line.reason_code, line.pending_count, line.completed_count])
        writer.writerow([])
        writer.writerow(["Reviewer", "Completed", "Completed Overdue", "Avg Review Hours"])
        for line in self.reviewer_line_ids:
            writer.writerow(
                [
                    line.reviewer_id.name or "",
                    line.completed_count,
                    line.overdue_completed_count,
                    round(line.avg_review_hours, 2),
                ]
            )

        data = output.getvalue().encode("utf-8")
        output.close()

        attachment = self.env["ir.attachment"].create(
            {
                "name": "manual_review_report.csv",
                "type": "binary",
                "datas": base64.b64encode(data),
                "mimetype": "text/csv",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }


class LabManualReviewReportLine(models.TransientModel):
    _name = "lab.manual.review.report.line"
    _description = "Manual Review Report Line"
    _order = "reason_code"

    wizard_id = fields.Many2one("lab.manual.review.report.wizard", required=True, ondelete="cascade")
    reason_code = fields.Char(readonly=True)
    pending_count = fields.Integer(readonly=True)
    completed_count = fields.Integer(readonly=True)


class LabManualReviewReviewerLine(models.TransientModel):
    _name = "lab.manual.review.reviewer.line"
    _description = "Manual Review Reviewer Line"
    _order = "completed_count desc, id"

    wizard_id = fields.Many2one("lab.manual.review.report.wizard", required=True, ondelete="cascade")
    reviewer_id = fields.Many2one("res.users", readonly=True)
    completed_count = fields.Integer(readonly=True)
    overdue_completed_count = fields.Integer(readonly=True)
    avg_review_hours = fields.Float(readonly=True)
