from datetime import timedelta

from odoo import _, api, fields, models


class LabPersonnelMatrixRun(models.Model):
    _name = "lab.personnel.matrix.run"
    _description = "Personnel Competency Matrix Run"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "run_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    run_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    run_by_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, readonly=True)
    period_days = fields.Integer(default=30, required=True)
    department = fields.Selection(
        [
            ("chemistry", "Clinical Chemistry"),
            ("hematology", "Hematology"),
            ("microbiology", "Microbiology"),
            ("immunology", "Immunology"),
            ("other", "Other"),
        ],
        string="Department Filter",
    )
    service_ids = fields.Many2many(
        "lab.service",
        "lab_personnel_matrix_run_service_rel",
        "run_id",
        "service_id",
        string="Service Filter",
    )
    include_analyst = fields.Boolean(default=True)
    include_technical_reviewer = fields.Boolean(default=True)
    include_medical_reviewer = fields.Boolean(default=True)
    line_ids = fields.One2many("lab.personnel.matrix.run.line", "run_id", string="Matrix Lines")

    total_lines = fields.Integer(compute="_compute_stats", store=True)
    authorized_lines = fields.Integer(compute="_compute_stats", store=True)
    warn_lines = fields.Integer(compute="_compute_stats", store=True)
    gap_lines = fields.Integer(compute="_compute_stats", store=True)

    @api.depends("line_ids.status")
    def _compute_stats(self):
        for rec in self:
            rec.total_lines = len(rec.line_ids)
            rec.authorized_lines = len(rec.line_ids.filtered(lambda l: l.status == "ok"))
            rec.warn_lines = len(rec.line_ids.filtered(lambda l: l.status == "warn"))
            rec.gap_lines = len(rec.line_ids.filtered(lambda l: l.status == "gap"))

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.personnel.matrix.run") or "New"
        return super().create(vals_list)

    def _matrix_domain_service(self):
        self.ensure_one()
        if not self.department:
            return []
        return [("department", "=", self.department)]

    def _collect_key_counts(self):
        self.ensure_one()
        start_dt = fields.Datetime.now() - timedelta(days=max(self.period_days, 0))
        rows = {}

        if self.service_ids:
            service_ids = set(self.service_ids.ids)
        else:
            service_domain = self._matrix_domain_service()
            service_ids = set(self.env["lab.service"].search(service_domain).ids) if service_domain else set()

        def _accept_service(service_id):
            return (not service_ids) or (service_id in service_ids)

        def _add(user_id, service_id, role, count=1):
            if not user_id or not service_id:
                return
            if not _accept_service(service_id):
                return
            key = (user_id, service_id, role)
            rows[key] = rows.get(key, 0) + count

        if self.include_analyst:
            analysis_rows = self.env["lab.sample.analysis"].search(
                [
                    ("analyst_id", "!=", False),
                    ("create_date", ">=", start_dt),
                    ("state", "in", ("done", "verified", "rejected")),
                ]
            )
            for row in analysis_rows:
                _add(row.analyst_id.id, row.service_id.id, "analyst", count=1)

        sample_rows = self.env["lab.sample"].search(
            [
                ("state", "in", ("verified", "reported")),
                "|",
                ("verified_date", ">=", start_dt),
                ("report_date", ">=", start_dt),
            ]
        )
        for sample in sample_rows:
            services = sample.analysis_ids.filtered(lambda a: a.state != "rejected").mapped("service_id")
            for service in services:
                if self.include_technical_reviewer and sample.technical_reviewer_id:
                    _add(sample.technical_reviewer_id.id, service.id, "technical_reviewer", count=1)
                if self.include_medical_reviewer and sample.medical_reviewer_id:
                    _add(sample.medical_reviewer_id.id, service.id, "medical_reviewer", count=1)
        return rows

    def action_generate_lines(self):
        auth_obj = self.env["lab.service.authorization"]
        today = fields.Date.today()
        warn_limit = today + timedelta(days=30)

        for rec in self:
            key_counts = rec._collect_key_counts()
            rec.line_ids.unlink()
            vals_list = []
            for (user_id, service_id, role), count in key_counts.items():
                current = auth_obj.search(
                    [
                        ("user_id", "=", user_id),
                        ("service_id", "=", service_id),
                        ("role", "=", role),
                        ("is_currently_authorized", "=", True),
                    ],
                    order="id desc",
                    limit=1,
                )
                latest = current or auth_obj.search(
                    [
                        ("user_id", "=", user_id),
                        ("service_id", "=", service_id),
                        ("role", "=", role),
                    ],
                    order="effective_to desc, id desc",
                    limit=1,
                )

                status = "gap"
                if current:
                    status = "warn" if (current.effective_to and current.effective_to <= warn_limit) else "ok"
                elif latest and latest.state == "approved" and latest.effective_to and latest.effective_to <= warn_limit:
                    status = "warn"

                vals_list.append(
                    {
                        "run_id": rec.id,
                        "user_id": user_id,
                        "service_id": service_id,
                        "role": role,
                        "activity_count": count,
                        "authorization_id": latest.id if latest else False,
                        "authorization_state": latest.state if latest else False,
                        "authorization_effective_to": latest.effective_to if latest else False,
                        "status": status,
                    }
                )

            if vals_list:
                self.env["lab.personnel.matrix.run.line"].create(vals_list)
            rec.message_post(
                body=_(
                    "Personnel matrix generated with %(total)s row(s), %(gap)s gap(s), %(warn)s warning(s)."
                )
                % {
                    "total": rec.total_lines,
                    "gap": rec.gap_lines,
                    "warn": rec.warn_lines,
                }
            )
        return True

    def action_view_gaps(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_personnel_matrix_run").sudo().read()[0]
        action["domain"] = [("id", "=", self.id)]
        action["context"] = {"search_default_f_status_gap": 1}
        return action

    @api.model
    def _cron_capture_personnel_matrix(self):
        exists = self.search_count([("run_date", ">=", fields.Datetime.now() - timedelta(hours=24))])
        if exists:
            return
        run = self.create(
            {
                "period_days": 30,
                "include_analyst": True,
                "include_technical_reviewer": True,
                "include_medical_reviewer": True,
            }
        )
        run.action_generate_lines()


class LabPersonnelMatrixRunLine(models.Model):
    _name = "lab.personnel.matrix.run.line"
    _description = "Personnel Competency Matrix Line"
    _order = "status desc, activity_count desc, id desc"

    run_id = fields.Many2one("lab.personnel.matrix.run", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, index=True)
    service_id = fields.Many2one("lab.service", required=True, index=True)
    role = fields.Selection(
        [
            ("analyst", "Analyst"),
            ("technical_reviewer", "Technical Reviewer"),
            ("medical_reviewer", "Medical Reviewer"),
        ],
        required=True,
    )
    activity_count = fields.Integer(default=0)
    authorization_id = fields.Many2one("lab.service.authorization", string="Latest Authorization")
    authorization_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending Approval"),
            ("approved", "Approved"),
            ("suspended", "Suspended"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ]
    )
    authorization_effective_to = fields.Date()
    status = fields.Selection(
        [
            ("ok", "Authorized"),
            ("warn", "Expiring Soon"),
            ("gap", "Authorization Gap"),
        ],
        required=True,
        default="gap",
    )
