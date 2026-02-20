import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabInterfaceEndpoint(models.Model):
    _name = "lab.interface.endpoint"
    _description = "LIS/HIS/Instrument Interface Endpoint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, tracking=True)
    system_type = fields.Selection(
        [("lis", "LIS"), ("his", "HIS"), ("instrument", "Instrument"), ("other", "Other")],
        required=True,
        default="his",
        tracking=True,
    )
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("bidirectional", "Bidirectional")],
        required=True,
        default="bidirectional",
    )
    protocol = fields.Selection(
        [("hl7v2", "HL7 v2.x"), ("fhir", "FHIR R4"), ("astm", "ASTM"), ("rest", "REST/JSON"), ("sftp", "SFTP")],
        required=True,
        default="rest",
    )
    auth_type = fields.Selection(
        [("none", "None"), ("basic", "Basic"), ("bearer", "Bearer"), ("api_key", "API Key")],
        default="none",
    )
    endpoint_url = fields.Char()
    inbound_url = fields.Char(compute="_compute_inbound_url")
    outbound_ack_url = fields.Char(compute="_compute_outbound_ack_url")
    username = fields.Char()
    password = fields.Char()
    token = fields.Char()
    api_key = fields.Char()
    outbound_mapping_profile_id = fields.Many2one(
        "lab.interface.mapping.profile",
        domain="[('direction','=','outbound'), ('active','=',True)]",
        string="Outbound Mapping Profile",
    )
    inbound_mapping_profile_id = fields.Many2one(
        "lab.interface.mapping.profile",
        domain="[('direction','=','inbound'), ('active','=',True)]",
        string="Inbound Mapping Profile",
    )
    allowed_ip_list = fields.Char(help="Comma separated source IP allow-list for inbound access.")
    auto_submit_inbound_order = fields.Boolean(default=True)
    auto_mark_done_inbound_result = fields.Boolean(default=False)
    dead_letter_enabled = fields.Boolean(default=True)
    timeout_seconds = fields.Integer(default=30)
    retry_limit = fields.Integer(default=3)
    mapping_schema = fields.Text(
        help="JSON mapping definition from internal fields to endpoint payload schema.",
    )
    active = fields.Boolean(default=True)
    note = fields.Text()
    job_ids = fields.One2many("lab.interface.job", "endpoint_id", string="Jobs", readonly=True)
    audit_log_ids = fields.One2many("lab.interface.audit.log", "endpoint_id", string="Audit Logs", readonly=True)
    success_count = fields.Integer(compute="_compute_job_stats")
    failed_count = fields.Integer(compute="_compute_job_stats")
    queued_count = fields.Integer(compute="_compute_job_stats")

    _code_uniq = models.Constraint("unique(code)", "Interface endpoint code must be unique.")

    @api.depends("code")
    def _compute_inbound_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        for rec in self:
            rec.inbound_url = ("%s/lab/interface/inbound/%s" % (base.rstrip("/"), rec.code)) if rec.code else False

    @api.depends("code")
    def _compute_outbound_ack_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        for rec in self:
            rec.outbound_ack_url = ("%s/lab/interface/outbound/%s/ack" % (base.rstrip("/"), rec.code)) if rec.code else False

    @api.depends("job_ids.state")
    def _compute_job_stats(self):
        for rec in self:
            rec.success_count = len(rec.job_ids.filtered(lambda j: j.state == "done"))
            rec.failed_count = len(rec.job_ids.filtered(lambda j: j.state in ("failed", "dead_letter")))
            rec.queued_count = len(rec.job_ids.filtered(lambda j: j.state in ("queued", "retry")))

    @api.constrains("retry_limit", "timeout_seconds")
    def _check_limits(self):
        for rec in self:
            if rec.retry_limit < 0 or rec.timeout_seconds <= 0:
                raise UserError(_("Retry limit must be >=0 and timeout must be >0."))

    def action_view_jobs(self):
        self.ensure_one()
        return {
            "name": _("Interface Jobs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.job",
            "view_mode": "list,form",
            "domain": [("endpoint_id", "=", self.id)],
            "context": {"default_endpoint_id": self.id},
        }

    def ingest_message(self, message_type, payload, external_uid=False, source_ip=False, raw_message=False):
        self.ensure_one()
        if self.direction not in ("inbound", "bidirectional"):
            raise UserError(_("Endpoint %s does not allow inbound messages.") % self.display_name)
        if self.allowed_ip_list and source_ip:
            allowed = {x.strip() for x in (self.allowed_ip_list or "").split(",") if x.strip()}
            if allowed and source_ip not in allowed:
                raise UserError(_("Source IP is not allowed for endpoint %s.") % self.display_name)

        if external_uid:
            existing = self.env["lab.interface.job"].search(
                [
                    ("endpoint_id", "=", self.id),
                    ("direction", "=", "inbound"),
                    ("external_uid", "=", external_uid),
                    ("state", "!=", "cancel"),
                ],
                limit=1,
            )
            if existing:
                self.env["lab.interface.audit.log"].log_event(
                    action="ingest",
                    direction="inbound",
                    endpoint=self,
                    job=existing,
                    external_uid=external_uid,
                    source_ip=source_ip,
                    payload=payload,
                    result={"deduplicated": True},
                    state=existing.state,
                )
                return existing

        job = self.env["lab.interface.job"].create(
            {
                "endpoint_id": self.id,
                "direction": "inbound",
                "message_type": message_type,
                "external_uid": external_uid or False,
                "payload_json": json.dumps(payload or {}, ensure_ascii=False, indent=2),
                "payload_text": raw_message or False,
                "source_ip": source_ip or False,
                "state": "queued",
            }
        )
        self.env["lab.interface.audit.log"].log_event(
            action="ingest",
            direction="inbound",
            endpoint=self,
            job=job,
            external_uid=external_uid,
            source_ip=source_ip,
            payload=payload,
            result={"queued": True},
            state=job.state,
        )
        job.action_process()
        return job

    def register_outbound_ack(
        self,
        *,
        ack_code,
        job_name=False,
        job_id=False,
        external_uid=False,
        ack_message=False,
        source_ip=False,
        payload=False,
    ):
        self.ensure_one()
        if self.direction not in ("outbound", "bidirectional"):
            raise UserError(_("Endpoint %s does not allow outbound acknowledgements.") % self.display_name)
        if self.allowed_ip_list and source_ip:
            allowed = {x.strip() for x in (self.allowed_ip_list or "").split(",") if x.strip()}
            if allowed and source_ip not in allowed:
                raise UserError(_("Source IP is not allowed for endpoint %s.") % self.display_name)
        if ack_code not in ("AA", "AE", "AR"):
            raise UserError(_("Unsupported ACK code %s.") % ack_code)

        domain = [("endpoint_id", "=", self.id), ("direction", "=", "outbound")]
        job = self.env["lab.interface.job"]
        if job_id:
            job = self.env["lab.interface.job"].search(domain + [("id", "=", int(job_id))], limit=1)
        if not job and job_name:
            job = self.env["lab.interface.job"].search(domain + [("name", "=", job_name)], limit=1)
        if not job and external_uid:
            job = self.env["lab.interface.job"].search(domain + [("external_uid", "=", external_uid)], limit=1)
        if not job:
            raise UserError(_("No outbound interface job matched the acknowledgement criteria."))

        return job.action_apply_ack(
            ack_code=ack_code,
            ack_message=ack_message or "",
            source_ip=source_ip or "",
            payload=payload or {},
        )


class LabInterfaceJob(models.Model):
    _name = "lab.interface.job"
    _description = "Lab Interface Job"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", copy=False, readonly=True)
    endpoint_id = fields.Many2one("lab.interface.endpoint", required=True, ondelete="cascade", index=True)
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        required=True,
        default="outbound",
    )
    message_type = fields.Selection(
        [
            ("order", "Order Message"),
            ("result", "Result Message"),
            ("report", "Report Message"),
            ("ack", "ACK/NACK"),
            ("patient", "Patient Master"),
            ("qc", "QC Message"),
        ],
        required=True,
        default="order",
    )
    state = fields.Selection(
        [
            ("queued", "Queued"),
            ("running", "Running"),
            ("done", "Done"),
            ("retry", "Retry"),
            ("failed", "Failed"),
            ("dead_letter", "Dead Letter"),
            ("cancel", "Cancelled"),
        ],
        default="queued",
        tracking=True,
    )
    request_id = fields.Many2one("lab.test.request", ondelete="set null")
    sample_id = fields.Many2one("lab.sample", ondelete="set null")
    import_job_id = fields.Many2one("lab.import.job", ondelete="set null")
    payload_text = fields.Text()
    payload_json = fields.Text()
    external_uid = fields.Char(index=True)
    source_ip = fields.Char(readonly=True)
    response_code = fields.Char(readonly=True)
    response_body = fields.Text(readonly=True)
    ack_code = fields.Selection([("AA", "AA"), ("AE", "AE"), ("AR", "AR")], readonly=True)
    ack_received_at = fields.Datetime(readonly=True)
    ack_source_ip = fields.Char(readonly=True)
    dead_letter_reason = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)
    queued_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    processed_at = fields.Datetime(readonly=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    next_retry_at = fields.Datetime()
    audit_log_ids = fields.One2many("lab.interface.audit.log", "job_id", string="Audit Logs", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = "IFJ/%s" % fields.Datetime.now().strftime("%Y%m%d%H%M%S")
        return super().create(vals_list)

    def _build_payload(self):
        self.ensure_one()
        if self.direction == "inbound":
            if self.payload_json:
                try:
                    return json.loads(self.payload_json)
                except Exception:  # noqa: BLE001
                    return {}
            return {}
        payload = {
            "job": self.name,
            "direction": self.direction,
            "message_type": self.message_type,
            "request": self.request_id.name if self.request_id else False,
            "sample": self.sample_id.name if self.sample_id else False,
        }
        if self.message_type == "order" and self.request_id:
            payload.update(
                {
                    "request_no": self.request_id.name,
                    "request_state": self.request_id.state,
                    "priority": self.request_id.priority,
                    "lines": [
                        {
                            "line_type": line.line_type,
                            "service_code": line.service_id.code if line.service_id else False,
                            "profile_code": line.profile_id.code if line.profile_id else False,
                            "qty": line.quantity,
                        }
                        for line in self.request_id.line_ids
                    ],
                }
            )
        if self.message_type in ("result", "report") and self.sample_id:
            payload.update(
                {
                    "accession": self.sample_id.name,
                    "state": self.sample_id.state,
                    "report_date": fields.Datetime.to_string(self.sample_id.report_date) if self.sample_id.report_date else False,
                    "results": [
                        {
                            "service_code": line.service_id.code,
                            "result": line.result_value,
                            "flag": line.result_flag,
                            "state": line.state,
                        }
                        for line in self.sample_id.analysis_ids
                    ],
                }
            )
        profile = self.endpoint_id.outbound_mapping_profile_id
        if profile and profile.message_type == self.message_type:
            return profile.map_payload(payload)
        return payload

    def _simulate_dispatch(self, payload):
        self.ensure_one()
        protocol = self.endpoint_id.protocol
        adapter = self.env["lab.protocol.adapter"]
        if protocol == "hl7v2":
            msg = adapter.build_hl7_message(payload, self.message_type, endpoint_code=self.endpoint_id.code, job_name=self.name)
            return "200", "AA|%s\n%s" % (self.name, msg)
        if protocol == "fhir":
            resource = adapter.build_fhir_resource(payload, self.message_type)
            return "200", adapter.to_json_text(resource)
        if protocol == "astm":
            return "200", "ASTM_ACK|%s" % self.name
        return "200", json.dumps({"status": "ok", "job": self.name, "payload": payload})

    def _extract_ack_code(self, response_code, response_body):
        self.ensure_one()
        code = str(response_code or "")
        body = response_body or ""
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="ignore")
        text = str(body).strip()
        if not text:
            return "AA"
        if self.endpoint_id.protocol == "hl7v2":
            upper = text.upper()
            for ack in ("|AA|", "|AE|", "|AR|"):
                if ack in upper:
                    return ack.strip("|")
            if upper.startswith("MSH|") and "\rMSA|AA|" in upper:
                return "AA"
            if upper.startswith("MSH|") and "\rMSA|AE|" in upper:
                return "AE"
            if upper.startswith("MSH|") and "\rMSA|AR|" in upper:
                return "AR"
            if upper.startswith("AA|"):
                return "AA"
            if upper.startswith("AE|"):
                return "AE"
            if upper.startswith("AR|"):
                return "AR"
            return "AA"
        if text.startswith("{") and text.endswith("}"):
            try:
                data = json.loads(text)
            except Exception:  # noqa: BLE001
                data = {}
            ack = (data.get("ack_code") or data.get("ack") or "").upper()
            if ack in ("AA", "AE", "AR"):
                return ack
            ok = data.get("ok")
            if ok is False:
                return "AE"
            if code and code.isdigit() and int(code) >= 400:
                return "AE"
            return "AA"
        if code and code.isdigit() and int(code) >= 400:
            return "AE"
        upper = text.upper()
        if upper.startswith("AE") or " ERROR" in upper:
            return "AE"
        if upper.startswith("AR") or " REJECT" in upper:
            return "AR"
        return "AA"

    def _process_inbound(self, payload):
        self.ensure_one()
        profile = self.endpoint_id.inbound_mapping_profile_id
        if profile and profile.message_type == self.message_type:
            payload = profile.map_payload(payload)
        if self.message_type == "order":
            partner = self.env.user.partner_id.commercial_partner_id
            requester = payload.get("requester_partner_id")
            partner_id = requester if isinstance(requester, int) else partner.id
            lines = []
            for item in payload.get("lines", []):
                service = False
                if item.get("service_code"):
                    service = self.env["lab.service"].search([("code", "=", item.get("service_code"))], limit=1)
                if not service:
                    continue
                lines.append(
                    (
                        0,
                        0,
                        {
                            "line_type": "service",
                            "service_id": service.id,
                            "quantity": int(item.get("qty") or 1),
                        },
                    )
                )
            if not lines:
                raise UserError(_("Inbound order has no valid service lines."))

            req = self.env["lab.test.request"].create(
                {
                    "requester_partner_id": partner_id,
                    "request_type": "individual",
                    "patient_name": payload.get("patient_name") or _("External Patient"),
                    "priority": payload.get("priority") or "routine",
                    "sample_type": payload.get("sample_type") or "blood",
                    "line_ids": lines,
                }
            )
            if self.endpoint_id.auto_submit_inbound_order:
                req.action_submit()
            self.request_id = req.id
            return "200", json.dumps({"status": "accepted", "request": req.name})

        if self.message_type in ("result", "report"):
            accession = payload.get("accession")
            if not accession:
                raise UserError(_("Inbound result payload requires accession."))
            sample = self.env["lab.sample"].search(
                ["|", ("name", "=", accession), ("accession_barcode", "=", accession)],
                limit=1,
            )
            if not sample:
                raise UserError(_("Sample not found for accession %s.") % accession)
            updated = 0
            for line in payload.get("results", []):
                service = self.env["lab.service"].search([("code", "=", line.get("service_code"))], limit=1)
                if not service:
                    continue
                analysis = sample.analysis_ids.filtered(lambda a: a.service_id == service)[:1]
                if not analysis:
                    continue
                analysis.write({"result_value": str(line.get("result") or ""), "result_note": line.get("note") or False})
                if self.endpoint_id.auto_mark_done_inbound_result and analysis.state in ("pending", "assigned"):
                    try:
                        analysis.action_mark_done()
                    except Exception:  # noqa: BLE001
                        pass
                updated += 1
            if not updated:
                raise UserError(_("No analysis lines were matched for inbound result message."))
            self.sample_id = sample.id
            self.request_id = sample.request_id.id
            return "200", json.dumps({"status": "accepted", "updated_lines": updated})

        return "200", json.dumps({"status": "accepted"})

    def action_process(self):
        for rec in self:
            if rec.state not in ("queued", "retry"):
                continue
            rec.write({"state": "running", "attempt_count": rec.attempt_count + 1})
            payload = rec._build_payload()
            rec.write({"payload_json": json.dumps(payload, ensure_ascii=False, indent=2)})
            try:
                if rec.direction == "inbound":
                    code, response = rec._process_inbound(payload)
                else:
                    code, response = rec._simulate_dispatch(payload)
                ack_code = rec._extract_ack_code(code, response)
                if ack_code in ("AE", "AR"):
                    raise UserError(_("Remote acknowledgement rejected message: %s") % (response or ack_code))
                rec.write(
                    {
                        "state": "done",
                        "response_code": code,
                        "response_body": response,
                        "ack_code": ack_code,
                        "processed_at": fields.Datetime.now(),
                        "error_message": False,
                        "dead_letter_reason": False,
                        "next_retry_at": False,
                    }
                )
                self.env["lab.interface.audit.log"].log_event(
                    action="process",
                    direction=rec.direction,
                    endpoint=rec.endpoint_id,
                    job=rec,
                    external_uid=rec.external_uid,
                    source_ip=rec.source_ip,
                    payload=payload,
                    result={"response_code": code, "response_body": response},
                    state=rec.state,
                )
            except Exception as err:  # noqa: BLE001
                rec._mark_failure(str(err))
        return True

    def _mark_failure(self, message):
        self.ensure_one()
        max_retry = self.endpoint_id.retry_limit
        if self.attempt_count >= max_retry:
            if self.endpoint_id.dead_letter_enabled:
                final_state = "dead_letter"
            else:
                final_state = "failed"
        else:
            final_state = "retry"
        values = {
            "state": final_state,
            "error_message": message,
            "ack_code": "AE" if final_state in ("retry", "failed") else "AR",
            "dead_letter_reason": message if final_state == "dead_letter" else False,
            "processed_at": fields.Datetime.now(),
            "next_retry_at": fields.Datetime.add(fields.Datetime.now(), minutes=10) if final_state == "retry" else False,
        }
        self.write(values)
        self.env["lab.interface.audit.log"].log_event(
            action="error",
            direction=self.direction,
            endpoint=self.endpoint_id,
            job=self,
            external_uid=self.external_uid,
            source_ip=self.source_ip,
            payload=self.payload_json or self.payload_text,
            result={"message": message},
            state=final_state,
        )

    def action_apply_ack(self, *, ack_code, ack_message=False, source_ip=False, payload=False):
        for rec in self:
            if rec.direction != "outbound":
                raise UserError(_("Only outbound jobs can apply remote acknowledgements."))
            if rec.state == "cancel":
                raise UserError(_("Cancelled job cannot receive acknowledgement updates."))
            payload_text = payload if isinstance(payload, str) else json.dumps(payload or {}, ensure_ascii=False, indent=2)
            rec.write(
                {
                    "ack_code": ack_code,
                    "ack_received_at": fields.Datetime.now(),
                    "ack_source_ip": source_ip or False,
                    "response_body": ack_message or rec.response_body,
                    "response_code": rec.response_code or "ACK",
                }
            )
            if ack_code in ("AE", "AR"):
                rec._mark_failure(ack_message or _("Remote system returned %s acknowledgement.") % ack_code)
            elif rec.state != "done":
                rec.write(
                    {
                        "state": "done",
                        "processed_at": fields.Datetime.now(),
                        "error_message": False,
                        "dead_letter_reason": False,
                        "next_retry_at": False,
                    }
                )
            self.env["lab.interface.audit.log"].log_event(
                action="ack",
                direction=rec.direction,
                endpoint=rec.endpoint_id,
                job=rec,
                external_uid=rec.external_uid,
                source_ip=source_ip,
                payload=payload_text or rec.payload_json or rec.payload_text,
                result={"ack_code": ack_code, "message": ack_message or ""},
                state=rec.state,
            )
        return True

    def action_requeue(self):
        for rec in self:
            if rec.state not in ("failed", "dead_letter", "cancel"):
                continue
            rec.write(
                {
                    "state": "queued",
                    "error_message": False,
                    "dead_letter_reason": False,
                    "response_code": False,
                    "response_body": False,
                    "ack_code": False,
                    "next_retry_at": False,
                }
            )
            self.env["lab.interface.audit.log"].log_event(
                action="requeue",
                direction=rec.direction,
                endpoint=rec.endpoint_id,
                job=rec,
                external_uid=rec.external_uid,
                source_ip=rec.source_ip,
                payload=rec.payload_json or rec.payload_text,
                result={"requeued": True},
                state=rec.state,
            )
        return True

    @api.model
    def action_process_pending(self, limit=100):
        now = fields.Datetime.now()
        jobs = self.search(
            [
                ("state", "in", ("queued", "retry")),
                "|",
                ("next_retry_at", "=", False),
                ("next_retry_at", "<=", now),
            ],
            order="id asc",
            limit=limit,
        )
        jobs.action_process()
        return True

    @api.model
    def _cron_process_interface_jobs(self):
        return self.action_process_pending(limit=200)


class LabTestRequestInterfaceMixin(models.Model):
    _inherit = "lab.test.request"

    interface_job_ids = fields.One2many("lab.interface.job", "request_id", string="Interface Jobs", readonly=True)
    interface_job_count = fields.Integer(compute="_compute_interface_job_count")

    def _compute_interface_job_count(self):
        for rec in self:
            rec.interface_job_count = len(rec.interface_job_ids)

    def _queue_interface_message(self, message_type):
        endpoint_obj = self.env["lab.interface.endpoint"]
        jobs = self.env["lab.interface.job"]
        for rec in self:
            endpoints = endpoint_obj.search(
                [
                    ("active", "=", True),
                    ("system_type", "in", ("lis", "his")),
                    ("direction", "in", ("outbound", "bidirectional")),
                ]
            )
            for endpoint in endpoints:
                jobs.create(
                    {
                        "endpoint_id": endpoint.id,
                        "direction": "outbound",
                        "message_type": message_type,
                        "request_id": rec.id,
                    }
                )

    def action_submit(self):
        result = super().action_submit()
        self._queue_interface_message("order")
        return result

    def action_view_interface_jobs(self):
        self.ensure_one()
        return {
            "name": _("Interface Jobs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.job",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }


class LabSampleInterfaceMixin(models.Model):
    _inherit = "lab.sample"

    interface_job_ids = fields.One2many("lab.interface.job", "sample_id", string="Interface Jobs", readonly=True)
    interface_job_count = fields.Integer(compute="_compute_interface_job_count")

    def _compute_interface_job_count(self):
        for rec in self:
            rec.interface_job_count = len(rec.interface_job_ids)

    def _queue_interface_report(self):
        endpoint_obj = self.env["lab.interface.endpoint"]
        for rec in self:
            endpoints = endpoint_obj.search(
                [
                    ("active", "=", True),
                    ("system_type", "in", ("lis", "his")),
                    ("direction", "in", ("outbound", "bidirectional")),
                ]
            )
            for endpoint in endpoints:
                self.env["lab.interface.job"].create(
                    {
                        "endpoint_id": endpoint.id,
                        "direction": "outbound",
                        "message_type": "report",
                        "sample_id": rec.id,
                        "request_id": rec.request_id.id,
                    }
                )

    def action_release_report(self):
        result = super().action_release_report()
        self._queue_interface_report()
        return result

    def action_view_interface_jobs(self):
        self.ensure_one()
        return {
            "name": _("Interface Jobs"),
            "type": "ir.actions.act_window",
            "res_model": "lab.interface.job",
            "view_mode": "list,form",
            "domain": [("sample_id", "=", self.id)],
            "context": {"default_sample_id": self.id},
        }
