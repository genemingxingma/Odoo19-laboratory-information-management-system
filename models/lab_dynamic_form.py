import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabDynamicForm(models.Model):
    _name = "lab.dynamic.form"
    _description = "Laboratory Dynamic Form"
    _inherit = ["mail.thread", "lab.master.data.mixin"]
    _order = "name, id"

    name = fields.Char(required=True, tracking=True, translate=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text(translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    field_ids = fields.One2many("lab.dynamic.form.field", "form_id", string="Fields")
    required_field_count = fields.Integer(compute="_compute_field_counts")
    total_field_count = fields.Integer(compute="_compute_field_counts")

    _sql_constraints = [
        ("lab_dynamic_form_code_company_uniq", "unique(code, company_id)", "Dynamic form code must be unique per company."),
    ]

    @api.depends("field_ids", "field_ids.required")
    def _compute_field_counts(self):
        for rec in self:
            rec.total_field_count = len(rec.field_ids)
            rec.required_field_count = len(rec.field_ids.filtered("required"))

    def to_portal_schema(self):
        self.ensure_one()
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description or "",
            "fields": [field.to_portal_schema() for field in self.field_ids.sorted("sequence") if field.active],
        }


class LabDynamicFormField(models.Model):
    _name = "lab.dynamic.form.field"
    _description = "Laboratory Dynamic Form Field"
    _order = "sequence, id"

    FIELD_TYPES = [
        ("text", "Text"),
        ("textarea", "Long Text"),
        ("number", "Number"),
        ("date", "Date"),
        ("datetime", "Datetime"),
        ("boolean", "Yes/No"),
        ("selection", "Single Choice"),
    ]

    form_id = fields.Many2one("lab.dynamic.form", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True, translate=True)
    key = fields.Char(required=True)
    field_type = fields.Selection(FIELD_TYPES, required=True, default="text")
    required = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    help_text = fields.Char(translate=True)
    placeholder = fields.Char(translate=True)
    selection_options = fields.Text(
        help="One option per line. Format: key:Label. Example:\nnone:No\nrecent:Recent contact",
    )

    _sql_constraints = [
        ("lab_dynamic_form_field_key_form_uniq", "unique(form_id, key)", "Field key must be unique within a form."),
    ]

    def parse_selection_options(self):
        self.ensure_one()
        result = []
        for row in (self.selection_options or "").splitlines():
            line = (row or "").strip()
            if not line:
                continue
            if ":" in line:
                key, label = line.split(":", 1)
            else:
                key, label = line, line
            key = key.strip()
            label = label.strip()
            if key:
                result.append({"key": key, "label": label or key})
        return result

    def to_portal_schema(self):
        self.ensure_one()
        return {
            "id": self.id,
            "key": self.key,
            "name": self.name,
            "field_type": self.field_type,
            "required": bool(self.required),
            "help_text": self.help_text or "",
            "placeholder": self.placeholder or "",
            "options": self.parse_selection_options() if self.field_type == "selection" else [],
        }


class LabServiceDynamicFormRel(models.Model):
    _name = "lab.service.dynamic.form.rel"
    _description = "Service Required Dynamic Form"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    service_id = fields.Many2one("lab.service", required=True, ondelete="cascade")
    form_id = fields.Many2one(
        "lab.dynamic.form",
        required=True,
        ondelete="restrict",
        domain="[('active','=',True), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one("res.company", related="service_id.company_id", store=True, readonly=True)

    _sql_constraints = [
        (
            "lab_service_dynamic_form_uniq",
            "unique(service_id, form_id)",
            "Each dynamic form can only be assigned once per service.",
        ),
    ]


class LabProfileDynamicFormRel(models.Model):
    _name = "lab.profile.dynamic.form.rel"
    _description = "Panel Required Dynamic Form"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    profile_id = fields.Many2one("lab.profile", required=True, ondelete="cascade")
    form_id = fields.Many2one(
        "lab.dynamic.form",
        required=True,
        ondelete="restrict",
        domain="[('active','=',True), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one("res.company", related="profile_id.company_id", store=True, readonly=True)

    _sql_constraints = [
        (
            "lab_profile_dynamic_form_uniq",
            "unique(profile_id, form_id)",
            "Each dynamic form can only be assigned once per panel.",
        ),
    ]


class LabServiceDynamicFormMixin(models.Model):
    _inherit = "lab.service"

    dynamic_form_rel_ids = fields.One2many("lab.service.dynamic.form.rel", "service_id", string="Required Forms")
    dynamic_form_ids = fields.Many2many(
        "lab.dynamic.form",
        compute="_compute_dynamic_form_ids",
        string="Required Forms",
    )

    @api.depends("dynamic_form_rel_ids.form_id")
    def _compute_dynamic_form_ids(self):
        for rec in self:
            rec.dynamic_form_ids = rec.dynamic_form_rel_ids.mapped("form_id")


class LabProfileDynamicFormMixin(models.Model):
    _inherit = "lab.profile"

    dynamic_form_rel_ids = fields.One2many("lab.profile.dynamic.form.rel", "profile_id", string="Required Forms")
    dynamic_form_ids = fields.Many2many(
        "lab.dynamic.form",
        compute="_compute_dynamic_form_ids",
        string="Required Forms",
    )

    @api.depends("dynamic_form_rel_ids.form_id")
    def _compute_dynamic_form_ids(self):
        for rec in self:
            rec.dynamic_form_ids = rec.dynamic_form_rel_ids.mapped("form_id")


class LabRequestDynamicFormResponse(models.Model):
    _name = "lab.request.dynamic.form.response"
    _description = "Request Dynamic Form Response"
    _order = "id"

    request_id = fields.Many2one("lab.test.request", required=True, ondelete="cascade", index=True)
    form_id = fields.Many2one("lab.dynamic.form", required=True, ondelete="restrict")
    line_ids = fields.One2many("lab.request.dynamic.form.response.line", "response_id", string="Answers", copy=True)
    is_complete = fields.Boolean(compute="_compute_is_complete", store=True)
    completed_at = fields.Datetime(readonly=True)
    completed_by_id = fields.Many2one("res.users", readonly=True)
    source = fields.Selection(
        [("auto", "Auto"), ("portal", "Portal"), ("api", "API"), ("manual", "Manual")],
        default="auto",
    )

    _sql_constraints = [
        (
            "lab_request_dynamic_form_response_uniq",
            "unique(request_id, form_id)",
            "Each required form should have only one response per request.",
        ),
    ]

    @api.depends(
        "line_ids",
        "line_ids.field_id.required",
        "line_ids.value_text",
        "line_ids.value_number",
        "line_ids.value_date",
        "line_ids.value_datetime",
        "line_ids.value_boolean",
        "line_ids.value_selection",
    )
    def _compute_is_complete(self):
        for rec in self:
            required_lines = rec.line_ids.filtered(lambda x: x.field_id.required)
            complete = True
            for line in required_lines:
                if not line.has_value():
                    complete = False
                    break
            rec.is_complete = complete

    def action_mark_complete(self):
        for rec in self:
            if not rec.is_complete:
                raise ValidationError(_("Cannot complete form response while required fields are empty."))
            rec.write(
                {
                    "completed_at": fields.Datetime.now(),
                    "completed_by_id": self.env.user.id,
                }
            )
        return True


class LabRequestDynamicFormResponseLine(models.Model):
    _name = "lab.request.dynamic.form.response.line"
    _description = "Request Dynamic Form Response Line"
    _order = "sequence, id"

    response_id = fields.Many2one("lab.request.dynamic.form.response", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    field_id = fields.Many2one("lab.dynamic.form.field", required=True, ondelete="restrict")
    field_key = fields.Char(related="field_id.key", store=True, readonly=True)
    field_name = fields.Char(related="field_id.name", store=True, readonly=True)
    field_type = fields.Selection(related="field_id.field_type", store=True, readonly=True)
    required = fields.Boolean(related="field_id.required", store=True, readonly=True)
    value_text = fields.Text()
    value_number = fields.Float()
    value_number_set = fields.Boolean(default=False)
    value_date = fields.Date()
    value_datetime = fields.Datetime()
    value_boolean = fields.Boolean()
    value_selection = fields.Char()
    display_value = fields.Char(compute="_compute_display_value")

    _sql_constraints = [
        (
            "lab_req_dynamic_form_response_line_uniq",
            "unique(response_id, field_id)",
            "Each field can be answered once per response.",
        ),
    ]

    @api.depends(
        "field_type",
        "value_text",
        "value_number",
        "value_number_set",
        "value_date",
        "value_datetime",
        "value_boolean",
        "value_selection",
    )
    def _compute_display_value(self):
        for rec in self:
            if rec.field_type in ("text", "textarea"):
                rec.display_value = (rec.value_text or "").strip()
            elif rec.field_type == "number":
                rec.display_value = "" if rec.value_number is False else str(rec.value_number)
            elif rec.field_type == "date":
                rec.display_value = rec.value_date.isoformat() if rec.value_date else ""
            elif rec.field_type == "datetime":
                rec.display_value = rec.value_datetime.isoformat() if rec.value_datetime else ""
            elif rec.field_type == "boolean":
                rec.display_value = _("Yes") if rec.value_boolean else _("No")
            elif rec.field_type == "selection":
                rec.display_value = rec.value_selection or ""
            else:
                rec.display_value = ""

    def has_value(self):
        self.ensure_one()
        if self.field_type in ("text", "textarea"):
            return bool((self.value_text or "").strip())
        if self.field_type == "number":
            return bool(self.value_number_set)
        if self.field_type == "date":
            return bool(self.value_date)
        if self.field_type == "datetime":
            return bool(self.value_datetime)
        if self.field_type == "boolean":
            return True
        if self.field_type == "selection":
            return bool((self.value_selection or "").strip())
        return False

    def write_from_payload(self, raw_value):
        self.ensure_one()
        value = raw_value
        if self.field_type in ("text", "textarea"):
            self.value_text = (value or "").strip()
            return
        if self.field_type == "number":
            if value in (None, ""):
                self.value_number = 0.0
                self.value_number_set = False
                return
            try:
                self.value_number = float(value)
                self.value_number_set = True
            except (TypeError, ValueError):
                raise ValidationError(
                    _("Field '%(field)s' expects a numeric value.")
                    % {"field": self.field_name}
                )
            return
        if self.field_type == "date":
            self.value_date = value or False
            return
        if self.field_type == "datetime":
            self.value_datetime = value or False
            return
        if self.field_type == "boolean":
            self.value_boolean = str(value).lower() in ("1", "true", "yes", "on")
            return
        if self.field_type == "selection":
            self.value_selection = (value or "").strip()
            return


class LabTestRequestDynamicFormMixin(models.Model):
    _inherit = "lab.test.request"

    dynamic_form_response_ids = fields.One2many(
        "lab.request.dynamic.form.response",
        "request_id",
        string="Dynamic Form Responses",
    )
    dynamic_form_required_count = fields.Integer(compute="_compute_dynamic_form_counts")
    dynamic_form_completed_count = fields.Integer(compute="_compute_dynamic_form_counts")

    @api.depends("dynamic_form_response_ids", "dynamic_form_response_ids.is_complete")
    def _compute_dynamic_form_counts(self):
        for rec in self:
            rec.dynamic_form_required_count = len(rec.dynamic_form_response_ids)
            rec.dynamic_form_completed_count = len(rec.dynamic_form_response_ids.filtered("is_complete"))

    def _required_dynamic_forms(self):
        self.ensure_one()
        forms = self.env["lab.dynamic.form"]
        service_forms = self.line_ids.mapped("service_id.dynamic_form_rel_ids.form_id").filtered(lambda x: x.active)
        profile_forms = self.line_ids.mapped("profile_id.dynamic_form_rel_ids.form_id").filtered(lambda x: x.active)
        forms |= service_forms | profile_forms
        return forms.filtered(lambda x: x.company_id == self.company_id)

    @api.model
    def validate_dynamic_form_payload(self, forms, payload):
        payload_dict = payload or {}
        for form in forms:
            values = payload_dict.get(form.code)
            if not isinstance(values, dict):
                raise ValidationError(
                    _("Required dynamic form '%(form)s' is missing.")
                    % {"form": form.name}
                )
            for field in form.field_ids.filtered(lambda x: x.active and x.required):
                raw = values.get(field.key)
                if field.field_type in ("text", "textarea", "selection"):
                    if not (str(raw or "").strip()):
                        raise ValidationError(
                            _("Field '%(field)s' is required in form '%(form)s'.")
                            % {"field": field.name, "form": form.name}
                        )
                elif field.field_type == "number":
                    if raw in (None, ""):
                        raise ValidationError(
                            _("Field '%(field)s' is required in form '%(form)s'.")
                            % {"field": field.name, "form": form.name}
                        )
                    try:
                        float(raw)
                    except (TypeError, ValueError):
                        raise ValidationError(
                            _("Field '%(field)s' in form '%(form)s' must be numeric.")
                            % {"field": field.name, "form": form.name}
                        )
                elif field.field_type in ("date", "datetime"):
                    if not raw:
                        raise ValidationError(
                            _("Field '%(field)s' is required in form '%(form)s'.")
                            % {"field": field.name, "form": form.name}
                        )

    def _sync_required_dynamic_forms(self):
        response_obj = self.env["lab.request.dynamic.form.response"]
        for rec in self:
            required_forms = rec._required_dynamic_forms()
            existing = {resp.form_id.id: resp for resp in rec.dynamic_form_response_ids}
            for form in required_forms:
                response = existing.get(form.id)
                if not response:
                    response = response_obj.create(
                        {
                            "request_id": rec.id,
                            "form_id": form.id,
                            "source": "auto",
                            "line_ids": [
                                (
                                    0,
                                    0,
                                    {
                                        "field_id": fld.id,
                                        "sequence": fld.sequence,
                                    },
                                )
                                for fld in form.field_ids.sorted("sequence")
                                if fld.active
                            ],
                        }
                    )
                    existing[form.id] = response
                else:
                    present = {line.field_id.id for line in response.line_ids}
                    to_add = form.field_ids.filtered(lambda f: f.active and f.id not in present)
                    if to_add:
                        response.write(
                            {
                                "line_ids": [
                                    (
                                        0,
                                        0,
                                        {
                                            "field_id": fld.id,
                                            "sequence": fld.sequence,
                                        },
                                    )
                                    for fld in to_add
                                ]
                            }
                        )

            obsolete = rec.dynamic_form_response_ids.filtered(lambda x: x.form_id.id not in required_forms.ids)
            if obsolete:
                obsolete.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_required_dynamic_forms()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "line_ids" in vals:
            self._sync_required_dynamic_forms()
        return res

    def _apply_dynamic_form_payload(self, payload, source="manual"):
        for rec in self:
            rec._sync_required_dynamic_forms()
            required_forms = {resp.form_id.code: resp for resp in rec.dynamic_form_response_ids}
            payload_dict = payload or {}
            for code, response in required_forms.items():
                form_payload = payload_dict.get(code) or {}
                for line in response.line_ids:
                    if line.field_key in form_payload:
                        line.write_from_payload(form_payload.get(line.field_key))
                response.source = source
                if response.is_complete and not response.completed_at:
                    response.completed_at = fields.Datetime.now()
                    response.completed_by_id = self.env.user.id

    def _check_required_dynamic_forms_complete(self):
        for rec in self:
            rec._sync_required_dynamic_forms()
            incomplete = rec.dynamic_form_response_ids.filtered(lambda x: not x.is_complete)
            if incomplete:
                raise ValidationError(
                    _("Dynamic forms are incomplete: %(forms)s")
                    % {"forms": ", ".join(incomplete.mapped("form_id.name"))}
                )

    def action_view_dynamic_form_responses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Form Responses"),
            "res_model": "lab.request.dynamic.form.response",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id},
        }

    def action_submit(self):
        self._check_required_dynamic_forms_complete()
        return super().action_submit()

    def get_dynamic_form_schema_json(self):
        self.ensure_one()
        forms = self._required_dynamic_forms()
        payload = {form.code: form.to_portal_schema() for form in forms}
        return json.dumps(payload, ensure_ascii=False)
