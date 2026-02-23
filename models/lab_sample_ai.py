import json
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


class LabSampleAIInterpretation(models.Model):
    _name = "lab.sample.ai.interpretation"
    _description = "Laboratory Sample AI Interpretation History"
    _order = "id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True)
    state = fields.Selection(
        [
            ("done", "Done"),
            ("error", "Error"),
        ],
        required=True,
        default="done",
        index=True,
    )
    trigger_source = fields.Selection(
        [
            ("manual", "Manual"),
            ("release", "Auto on Release"),
            ("queue", "Queued Worker"),
            ("portal", "Portal"),
            ("cron", "Scheduled Retry"),
        ],
        default="manual",
        required=True,
        index=True,
    )
    model_name = fields.Char(string="Model")
    output_language = fields.Char()
    duration_ms = fields.Integer(string="Duration (ms)")
    prompt_tokens = fields.Integer()
    completion_tokens = fields.Integer()
    total_tokens = fields.Integer()
    system_prompt = fields.Text()
    user_prompt = fields.Text()
    response_text = fields.Text()
    error_text = fields.Text()
    generated_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_sample_ai_history_sample_generated
            ON lab_sample_ai_interpretation (sample_id, generated_at DESC)
            """
        )
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_sample_ai_history_state_generated
            ON lab_sample_ai_interpretation (state, generated_at DESC)
            """
        )


class LabSampleAIReviewLog(models.Model):
    _name = "lab.sample.ai.review.log"
    _description = "Laboratory Sample AI Review Timeline"
    _order = "id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True)
    action = fields.Selection(
        [
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("reopened", "Reopened"),
        ],
        required=True,
        index=True,
    )
    reviewer_id = fields.Many2one("res.users", required=True, index=True)
    note = fields.Text()
    reviewed_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)

    def init(self):
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lab_sample_ai_review_sample_reviewed
            ON lab_sample_ai_review_log (sample_id, reviewed_at DESC)
            """
        )


class LabSample(models.Model):
    _inherit = "lab.sample"

    ai_interpretation_state = fields.Selection(
        [
            ("none", "Not Generated"),
            ("queued", "Queued"),
            ("running", "Running"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="none",
        readonly=True,
        tracking=True,
    )
    ai_interpretation_text = fields.Text(readonly=True)
    ai_interpretation_error = fields.Text(readonly=True)
    ai_interpretation_model = fields.Char(readonly=True)
    ai_interpretation_lang = fields.Char(readonly=True)
    ai_interpretation_prompt = fields.Text(readonly=True)
    ai_interpretation_updated_at = fields.Datetime(readonly=True)
    ai_review_state = fields.Selection(
        [
            ("none", "No Review"),
            ("pending", "Pending Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="none",
        readonly=True,
        tracking=True,
    )
    ai_reviewed_by_id = fields.Many2one("res.users", string="AI Reviewed By", readonly=True, tracking=True)
    ai_reviewed_at = fields.Datetime(string="AI Reviewed At", readonly=True, tracking=True)
    ai_review_note = fields.Text(string="AI Review Note")
    ai_portal_visible = fields.Boolean(
        compute="_compute_ai_portal_visible",
        string="AI Visible in Portal",
    )
    ai_review_log_ids = fields.One2many(
        "lab.sample.ai.review.log",
        "sample_id",
        string="AI Review Timeline",
        readonly=True,
    )
    ai_interpretation_history_ids = fields.One2many(
        "lab.sample.ai.interpretation",
        "sample_id",
        string="AI Interpretation History",
        readonly=True,
    )
    ai_interpretation_history_count = fields.Integer(compute="_compute_ai_interpretation_history_count")

    def _selection_label(self, field_name, value):
        """Return selection label safely for static/callable/method-name selections."""
        if not value:
            return ""
        field = self._fields.get(field_name)
        if not field:
            return value
        selection = field.selection
        if isinstance(selection, str):
            selection = getattr(self, selection)()
        elif callable(selection):
            selection = selection(self.env)
        mapping = dict(selection or [])
        return mapping.get(value, value)

    def _compute_ai_interpretation_history_count(self):
        for rec in self:
            rec.ai_interpretation_history_count = len(rec.ai_interpretation_history_ids)

    def _compute_ai_portal_visible(self):
        for rec in self:
            rec.ai_portal_visible = bool(
                rec.ai_review_state == "approved" and rec.ai_interpretation_state == "done" and rec.ai_interpretation_text
            )

    def action_view_ai_interpretation_history(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_sample_ai_interpretation").sudo().read()[0]
        action["domain"] = [("sample_id", "=", self.id)]
        action["context"] = {
            "default_sample_id": self.id,
            "search_default_sample_id": self.id,
        }
        return action

    def _create_ai_review_log(self, action, note=None):
        self.ensure_one()
        self.env["lab.sample.ai.review.log"].sudo().create(
            {
                "sample_id": self.id,
                "action": action,
                "reviewer_id": self.env.user.id,
                "note": note or False,
                "reviewed_at": fields.Datetime.now(),
            }
        )

    def _schedule_ai_review_activity(self):
        summary = "AI Interpretation Review"
        reviewer_group = self.env.ref("laboratory_management.group_lab_reviewer", raise_if_not_found=False)
        users = reviewer_group.user_ids if reviewer_group else self.env.user
        helper = self.env["lab.activity.helper.mixin"]
        entries = []
        for rec in self:
            note = _("Review and approve/reject AI interpretation for sample %s.") % rec.name
            for user in users:
                entries.append({"res_id": rec.id, "user_id": user.id, "summary": summary, "note": note})
        helper.create_unique_todo_activities(model_name="lab.sample", entries=entries)

    def _close_ai_review_activity(self):
        summary = "AI Interpretation Review"
        model_id = self.env["ir.model"]._get_id("lab.sample")
        activities = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", self.ids),
                ("summary", "=", summary),
            ]
        )
        activities.action_feedback(feedback=_("AI interpretation review completed."))

    def _get_output_language(self):
        self.ensure_one()
        lang = (
            self.patient_id.lang
            or (self.patient_id.partner_id.lang if self.patient_id.partner_id else False)
            or self.env.context.get("lang")
            or self.env.user.lang
            or "en_US"
        )
        if lang.startswith("zh"):
            return "Chinese"
        if lang.startswith("th"):
            return "Thai"
        return "English"

    def _build_prompt_context(self):
        self.ensure_one()
        analysis_lines = []
        abnormal_lines = []

        def _line_label(line, field_name, value):
            if not value:
                return ""
            field = line._fields.get(field_name)
            if not field:
                return value
            selection = field.selection
            if isinstance(selection, str):
                selection = getattr(line, selection)()
            elif callable(selection):
                selection = selection(line.env)
            return dict(selection or []).get(value, value)

        for line in self.analysis_ids:
            flag = _line_label(line, "result_flag", line.result_flag) if line.result_flag else "N/A"
            state = _line_label(line, "state", line.state) if line.state else "N/A"
            item = "- {service}: result={result} {unit}; range={rmin}-{rmax}; flag={flag}; status={state}".format(
                service=line.service_id.name,
                result=line.result_value or "N/A",
                unit=line.unit or "",
                rmin=line.ref_min if line.ref_min is not None else "N/A",
                rmax=line.ref_max if line.ref_max is not None else "N/A",
                flag=flag,
                state=state,
            )
            analysis_lines.append(item)
            if line.result_flag in ("high", "low", "critical"):
                abnormal_lines.append(item)

        if not abnormal_lines:
            abnormal_lines = ["- No clearly abnormal item detected by current rule."]

        output_language = self._get_output_language()
        report_snapshot = (
            "Report Summary\n"
            "Accession: {accession}\n"
            "Patient: {patient_name}\n"
            "Client: {client_name}\n"
            "Physician: {physician_name}\n"
            "Template: {report_template}\n"
            "Status: {state}\n"
            "Priority: {priority}\n"
            "Collection Date: {collection_date}\n"
            "Verified Date: {verified_date}\n"
            "Report Date: {report_date}\n"
            "Revision: {report_revision}\n"
            "Amended: {is_amended}\n"
            "\n"
            "Results:\n{analysis_lines}\n"
            "\n"
            "Abnormal:\n{abnormal_lines}\n"
        ).format(
            accession=self.name or "",
            patient_name=self.patient_id.name or "",
            client_name=self.client_id.name or "",
            physician_name=self.physician_name or "",
            report_template=self.report_template_id.name or "",
            state=self._selection_label("state", self.state) if self.state else "",
            priority=self._selection_label("priority", self.priority) if self.priority else "",
            collection_date=self.collection_date or "",
            verified_date=self.verified_date or "",
            report_date=self.report_date or "",
            report_revision=self.report_revision or 0,
            is_amended="Yes" if self.is_amended else "No",
            analysis_lines="\n".join(analysis_lines) or "- No analysis records",
            abnormal_lines="\n".join(abnormal_lines),
        )

        return _SafeDict(
            {
                "sample_name": self.name or "",
                "accession": self.name or "",
                "patient_name": self.patient_id.name or "",
                "client_name": self.client_id.name or "",
                "physician_name": self.physician_name or "",
                "report_template": self.report_template_id.name or "",
                "priority": self._selection_label("priority", self.priority) if self.priority else "",
                "state": self._selection_label("state", self.state) if self.state else "",
                "collection_date": self.collection_date or "",
                "report_date": self.report_date or "",
                "verified_date": self.verified_date or "",
                "analysis_lines": "\n".join(analysis_lines) or "- No analysis records",
                "abnormal_lines": "\n".join(abnormal_lines),
                "analysis_count": len(analysis_lines),
                "abnormal_count": len([x for x in abnormal_lines if not x.startswith("- No clearly abnormal")]),
                "report_revision": self.report_revision or 0,
                "is_amended": "Yes" if self.is_amended else "No",
                "output_language": output_language,
                "sample_note": self.note or "",
                "amendment_note": self.amendment_note or "",
                "template_note": self.report_template_id.note or "",
                "report_snapshot": report_snapshot,
            }
        )

    def _build_ai_prompt(self):
        self.ensure_one()
        template = self.report_template_id
        context_map = self._build_prompt_context()

        user_prompt_template = template.ai_user_prompt_template if template else False
        if not user_prompt_template:
            user_prompt_template = (
                "Sample: {sample_name}\n"
                "Patient: {patient_name}\n"
                "Report Date: {report_date}\n"
                "\n"
                "Analysis Results:\n{analysis_lines}\n"
                "\n"
                "Abnormal Items:\n{abnormal_lines}\n"
                "\n"
                "Please provide concise educational interpretation. "
                "Output language: {output_language}."
            )

        prompt = user_prompt_template.format_map(context_map)
        output_language = context_map.get("output_language")
        return prompt, output_language

    def _create_ai_history(
        self,
        *,
        state,
        trigger_source,
        model_name=None,
        output_language=None,
        duration_ms=None,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        system_prompt=None,
        user_prompt=None,
        response_text=None,
        error_text=None,
    ):
        self.ensure_one()
        self.env["lab.sample.ai.interpretation"].sudo().create(
            {
                "sample_id": self.id,
                "state": state,
                "trigger_source": trigger_source or "manual",
                "model_name": model_name,
                "output_language": output_language,
                "duration_ms": duration_ms,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_text": response_text,
                "error_text": error_text,
                "generated_at": fields.Datetime.now(),
            }
        )

    def _get_ai_provider_and_model(self):
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        provider = (config.get_param("laboratory_management.ai_provider") or "openai").strip()
        if provider == "openai_compatible":
            model_name = (config.get_param("laboratory_management.openai_compatible_model") or "").strip()
            if not model_name:
                model_name = (config.get_param("laboratory_management.openai_model") or "gpt-4.1-mini").strip()
        elif provider == "ollama":
            model_name = (config.get_param("laboratory_management.ollama_model") or "llama3.1:8b").strip()
        else:
            provider = "openai"
            model_name = (config.get_param("laboratory_management.openai_model") or "gpt-4.1-mini").strip()
        return provider, model_name

    def _call_ai_provider(self, *, prompt, system_prompt, temperature):
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        provider, model_name = self._get_ai_provider_and_model()
        timeout_seconds = int((config.get_param("laboratory_management.ai_timeout_seconds") or "120").strip())

        if provider == "ollama":
            base_url = (config.get_param("laboratory_management.ollama_base_url") or "http://127.0.0.1:11434/api/chat").strip()
            body = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                },
            }
            response = requests.post(base_url, json=body, timeout=timeout_seconds)
            if response.status_code >= 400:
                raise UserError(_("Ollama API request failed: %s") % response.text[:500])
            result = response.json() if response.content else {}
            message = result.get("message", {}) if isinstance(result, dict) else {}
            content = message.get("content") or result.get("response")
            if not content:
                raise UserError(_("Ollama API returned empty interpretation."))
            usage = {
                "prompt_tokens": result.get("prompt_eval_count") or 0,
                "completion_tokens": result.get("eval_count") or 0,
                "total_tokens": (result.get("prompt_eval_count") or 0) + (result.get("eval_count") or 0),
            }
            return content, result.get("model") or model_name, usage

        if provider == "openai_compatible":
            api_key = (config.get_param("laboratory_management.openai_compatible_api_key") or "").strip()
            base_url = (
                config.get_param("laboratory_management.openai_compatible_base_url")
                or "http://127.0.0.1:8000/v1/chat/completions"
            ).strip()
        else:
            api_key = (config.get_param("laboratory_management.openai_api_key") or "").strip()
            base_url = (
                config.get_param("laboratory_management.openai_base_url") or "https://api.openai.com/v1/chat/completions"
            ).strip()
            if not api_key:
                raise UserError(
                    _(
                        "OpenAI API key is not configured. Set system parameter: "
                        "laboratory_management.openai_api_key"
                    )
                )

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer %s" % api_key
        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }

        response = requests.post(base_url, headers=headers, json=body, timeout=timeout_seconds)
        if response.status_code >= 400:
            raise UserError(_("AI API request failed: %s") % response.text[:500])

        result = response.json() if response.content else {}
        content = result.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(result, dict) else False
        if not content:
            raise UserError(_("AI API returned empty interpretation."))
        usage = result.get("usage", {}) if isinstance(result, dict) else {}
        return content, model_name, usage

    def _generate_ai_interpretation_internal(self):
        self.ensure_one()
        if self.state not in ("verified", "reported"):
            raise UserError(_("AI interpretation is only available for verified/reported samples."))

        template = self.report_template_id
        if template and not template.ai_interpretation_enabled:
            return False

        trigger_source = self.env.context.get("ai_trigger_source") or "manual"
        if trigger_source == "portal" and self.ai_review_state == "approved":
            raise UserError(_("AI interpretation is locked after approval and cannot be refreshed from portal."))
        started = time.monotonic()

        prompt, output_lang = self._build_ai_prompt()
        system_prompt = (
            (template.ai_system_prompt or "").strip() if template else "You are a laboratory report interpretation assistant."
        )
        if not system_prompt:
            system_prompt = "You are a laboratory report interpretation assistant."
        temperature = template.ai_temperature if template else 0.2

        self.write(
            {
                "ai_interpretation_state": "running",
                "ai_interpretation_error": False,
            }
        )

        content, model_name, usage = self._call_ai_provider(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        prompt_tokens = usage.get("prompt_tokens") or 0
        completion_tokens = usage.get("completion_tokens") or 0
        total_tokens = usage.get("total_tokens") or 0
        duration_ms = int((time.monotonic() - started) * 1000)

        was_approved = self.ai_review_state == "approved"
        self.write(
            {
                "ai_interpretation_state": "done",
                "ai_interpretation_text": content,
                "ai_interpretation_error": False,
                "ai_interpretation_model": model_name,
                "ai_interpretation_lang": output_lang,
                "ai_interpretation_prompt": prompt,
                "ai_interpretation_updated_at": fields.Datetime.now(),
                "ai_review_state": "pending",
                "ai_reviewed_by_id": False,
                "ai_reviewed_at": False,
            }
        )
        if was_approved:
            self._create_ai_review_log(action="reopened", note=_("Interpretation changed and requires re-approval."))
        self._schedule_ai_review_activity()
        self._create_ai_history(
            state="done",
            trigger_source=trigger_source,
            model_name=model_name,
            output_language=output_lang,
            duration_ms=duration_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            system_prompt=system_prompt,
            user_prompt=prompt,
            response_text=content,
        )
        self.message_post(body=_("AI interpretation generated (model: %s)") % model_name)
        return True

    def action_generate_ai_interpretation(self):
        force = bool(self.env.context.get("force_ai_regenerate"))
        silent = bool(self.env.context.get("ai_silent"))
        trigger_source = self.env.context.get("ai_trigger_source") or "manual"
        for rec in self:
            if rec.ai_interpretation_state == "done" and rec.ai_interpretation_text and not force:
                continue
            started = time.monotonic()
            try:
                rec._generate_ai_interpretation_internal()
            except Exception as exc:
                duration_ms = int((time.monotonic() - started) * 1000)
                prompt = False
                output_lang = False
                system_prompt = False
                try:
                    prompt, output_lang = rec._build_ai_prompt()
                    template = rec.report_template_id
                    system_prompt = (
                        (template.ai_system_prompt or "").strip()
                        if template
                        else "You are a laboratory report interpretation assistant."
                    )
                except Exception:
                    pass

                rec.write(
                    {
                        "ai_interpretation_state": "error",
                        "ai_interpretation_error": str(exc),
                        "ai_interpretation_updated_at": fields.Datetime.now(),
                    }
                )
                rec._create_ai_history(
                    state="error",
                    trigger_source=trigger_source,
                    model_name=rec._get_ai_provider_and_model()[1],
                    output_language=output_lang,
                    duration_ms=duration_ms,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    error_text=str(exc),
                )
                if not silent:
                    raise
        return True

    def action_queue_ai_interpretation(self, force=False, trigger_source="release"):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state not in ("verified", "reported"):
                continue
            if rec.ai_interpretation_state == "done" and rec.ai_interpretation_text and not force:
                continue
            rec.write(
                {
                    "ai_interpretation_state": "queued",
                    "ai_interpretation_error": False,
                    "ai_interpretation_updated_at": now,
                }
            )
        return True

    def action_clear_ai_interpretation(self):
        self.write(
            {
                "ai_interpretation_state": "none",
                "ai_interpretation_text": False,
                "ai_interpretation_error": False,
                "ai_interpretation_model": False,
                "ai_interpretation_lang": False,
                "ai_interpretation_prompt": False,
                "ai_interpretation_updated_at": False,
                "ai_review_state": "none",
                "ai_reviewed_by_id": False,
                "ai_reviewed_at": False,
                "ai_review_note": False,
            }
        )

    def action_approve_ai_interpretation(self):
        for rec in self:
            if rec.ai_interpretation_state != "done" or not rec.ai_interpretation_text:
                raise UserError(_("Only generated AI interpretation can be approved."))
            rec.write(
                {
                    "ai_review_state": "approved",
                    "ai_reviewed_by_id": self.env.user.id,
                    "ai_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_ai_review_log(action="approved", note=rec.ai_review_note)
            rec._close_ai_review_activity()
            rec.message_post(body=_("AI interpretation approved for portal/report display."))
        return True

    def action_reject_ai_interpretation(self):
        for rec in self:
            if rec.ai_interpretation_state not in ("done", "error"):
                raise UserError(_("Only generated AI interpretation can be rejected."))
            if not (rec.ai_review_note or "").strip():
                raise UserError(_("Rejection reason is required. Please fill AI Review Note before rejecting."))
            rec.write(
                {
                    "ai_review_state": "rejected",
                    "ai_reviewed_by_id": self.env.user.id,
                    "ai_reviewed_at": fields.Datetime.now(),
                }
            )
            rec._create_ai_review_log(action="rejected", note=rec.ai_review_note)
            rec._close_ai_review_activity()
            rec.message_post(body=_("AI interpretation rejected from portal/report display."))
        return True

    def action_release_report(self):
        result = super().action_release_report()
        config = self.env["ir.config_parameter"].sudo()
        async_on_release = (config.get_param("laboratory_management.ai_async_on_release", "1") or "1").strip()
        use_async = async_on_release not in ("0", "false", "False")
        for rec in self:
            template = rec.report_template_id
            if not template or not template.ai_interpretation_enabled or not template.ai_auto_generate_on_release:
                continue
            if use_async:
                rec.action_queue_ai_interpretation(force=True, trigger_source="release")
            else:
                rec.with_context(
                    ai_silent=True,
                    force_ai_regenerate=True,
                    ai_trigger_source="release",
                ).action_generate_ai_interpretation()
        return result

    @api.model
    def _cron_process_ai_interpretation_queue(self):
        config = self.env["ir.config_parameter"].sudo()
        limit = int((config.get_param("laboratory_management.ai_queue_batch_size") or "50").strip())
        queued = self.search(
            [
                ("state", "in", ("verified", "reported")),
                ("ai_interpretation_state", "=", "queued"),
            ],
            limit=limit,
            order="ai_interpretation_updated_at asc, id asc",
        )
        for rec in queued:
            rec.with_context(
                ai_silent=True,
                force_ai_regenerate=True,
                ai_trigger_source="queue",
            ).action_generate_ai_interpretation()

    @api.model
    def _cron_retry_ai_interpretation_errors(self):
        config = self.env["ir.config_parameter"].sudo()
        enabled = (config.get_param("laboratory_management.ai_retry_enabled") or "1").strip()
        if enabled in ("0", "false", "False"):
            return

        retry_limit = int((config.get_param("laboratory_management.ai_retry_limit") or "20").strip())
        records = self.search(
            [
                ("state", "in", ("verified", "reported")),
                ("ai_interpretation_state", "=", "error"),
            ],
            limit=retry_limit,
            order="ai_interpretation_updated_at asc, id asc",
        )
        for rec in records:
            rec.with_context(
                ai_silent=True,
                force_ai_regenerate=True,
                ai_trigger_source="cron",
            ).action_generate_ai_interpretation()

    def _dump_ai_history_json(self, limit=20):
        self.ensure_one()
        data = []
        for line in self.ai_interpretation_history_ids[:limit]:
            data.append(
                {
                    "id": line.id,
                    "state": line.state,
                    "trigger_source": line.trigger_source,
                    "model_name": line.model_name,
                    "output_language": line.output_language,
                    "duration_ms": line.duration_ms,
                    "prompt_tokens": line.prompt_tokens,
                    "completion_tokens": line.completion_tokens,
                    "total_tokens": line.total_tokens,
                    "generated_at": line.generated_at.isoformat() if line.generated_at else None,
                    "error_text": line.error_text,
                }
            )
        return json.dumps(data, ensure_ascii=False, indent=2)


class ResConfigSettingsAI(models.TransientModel):
    _inherit = "res.config.settings"

    lab_ai_provider = fields.Selection(
        [
            ("openai", "OpenAI"),
            ("openai_compatible", "OpenAI-Compatible"),
            ("ollama", "Ollama"),
        ],
        string="AI Provider",
        config_parameter="laboratory_management.ai_provider",
        default="openai",
    )
    lab_openai_api_key = fields.Char(
        string="OpenAI API Key",
        config_parameter="laboratory_management.openai_api_key",
    )
    lab_openai_model = fields.Char(
        string="OpenAI Model",
        config_parameter="laboratory_management.openai_model",
        default="gpt-4.1-mini",
    )
    lab_openai_base_url = fields.Char(
        string="OpenAI Base URL",
        config_parameter="laboratory_management.openai_base_url",
        default="https://api.openai.com/v1/chat/completions",
    )
    lab_openai_compatible_api_key = fields.Char(
        string="OpenAI-Compatible API Key",
        config_parameter="laboratory_management.openai_compatible_api_key",
    )
    lab_openai_compatible_model = fields.Char(
        string="OpenAI-Compatible Model",
        config_parameter="laboratory_management.openai_compatible_model",
        default="gpt-4.1-mini",
    )
    lab_openai_compatible_base_url = fields.Char(
        string="OpenAI-Compatible Base URL",
        config_parameter="laboratory_management.openai_compatible_base_url",
        default="http://127.0.0.1:8000/v1/chat/completions",
    )
    lab_ollama_model = fields.Char(
        string="Ollama Model",
        config_parameter="laboratory_management.ollama_model",
        default="llama3.1:8b",
    )
    lab_ollama_base_url = fields.Char(
        string="Ollama Base URL",
        config_parameter="laboratory_management.ollama_base_url",
        default="http://127.0.0.1:11434/api/chat",
    )
    lab_ai_timeout_seconds = fields.Integer(
        string="AI Request Timeout (seconds)",
        config_parameter="laboratory_management.ai_timeout_seconds",
        default=120,
    )
    lab_ai_retry_enabled = fields.Boolean(
        string="Retry Failed AI Interpretation Jobs",
        config_parameter="laboratory_management.ai_retry_enabled",
        default=True,
    )
    lab_ai_retry_limit = fields.Integer(
        string="Retry Batch Size",
        config_parameter="laboratory_management.ai_retry_limit",
        default=20,
    )
    lab_ai_async_on_release = fields.Boolean(
        string="Generate AI Asynchronously on Report Release",
        config_parameter="laboratory_management.ai_async_on_release",
        default=True,
    )
    lab_ai_queue_batch_size = fields.Integer(
        string="AI Queue Batch Size",
        config_parameter="laboratory_management.ai_queue_batch_size",
        default=50,
    )
    lab_report_pdf_cache_on_release = fields.Boolean(
        string="Cache Report PDF on Release",
        config_parameter="laboratory_management.report_pdf_cache_on_release",
        default=True,
    )
