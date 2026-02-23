from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LabMasterDataMixin(models.AbstractModel):
    _name = "lab.master.data.mixin"
    _description = "Laboratory Master Data Mixin"

    @api.model
    def _selection_from_master(self, model_name, fallback):
        records = self.env[model_name].sudo().search([("active", "=", True)], order="sequence asc, id asc")
        if records:
            return [(rec.code, rec.name) for rec in records]
        return fallback

    @api.model
    def _default_from_master(self, model_name, fallback_code):
        default_rec = self.env[model_name].sudo().search([("active", "=", True), ("is_default", "=", True)], limit=1)
        if default_rec:
            return default_rec.code
        first_rec = self.env[model_name].sudo().search([("active", "=", True)], order="sequence asc, id asc", limit=1)
        return first_rec.code if first_rec else fallback_code

    @api.model
    def _selection_department(self):
        return self._selection_from_master(
            "lab.department.type",
            [
                ("chemistry", "Clinical Chemistry"),
                ("hematology", "Hematology"),
                ("microbiology", "Microbiology"),
                ("immunology", "Immunology"),
                ("other", "Other"),
            ],
        )

    @api.model
    def _selection_sample_type(self):
        return self._selection_from_master(
            "lab.sample.type",
            [
                ("blood", "Whole Blood"),
                ("urine", "Urine"),
                ("stool", "Stool"),
                ("swab", "Swab"),
                ("serum", "Serum"),
                ("other", "Other"),
            ],
        )

    @api.model
    def _selection_priority(self):
        return self._selection_from_master(
            "lab.priority.type",
            [("routine", "Routine"), ("urgent", "Urgent"), ("stat", "STAT")],
        )

    @api.model
    def _selection_request_type(self):
        records = (
            self.env["lab.request.type"]
            .sudo()
            .search(
                [
                    ("active", "=", True),
                    ("code", "in", ["individual", "institution"]),
                ],
                order="sequence asc, id asc",
            )
        )
        if records:
            values = [(rec.code, rec.name) for rec in records]
            if {"individual", "institution"}.issubset({code for code, _name in values}):
                return values
        return [("individual", "Individual"), ("institution", "Institution")]

    @api.model
    def _selection_result_unit(self):
        return self._selection_from_master(
            "lab.result.unit",
            [("none", "No Unit"), ("percent", "%"), ("count", "count")],
        )

    @api.model
    def _default_department_code(self):
        return self._default_from_master("lab.department.type", "chemistry")

    @api.model
    def _default_sample_type_code(self):
        return self._default_from_master("lab.sample.type", "blood")

    @api.model
    def _default_priority_code(self):
        return self._default_from_master("lab.priority.type", "routine")

    @api.model
    def _default_request_type_code(self):
        return self._default_from_master("lab.request.type", "individual")

    @api.model
    def seed_i18n_master_data(self):
        """Seed core master-data names in EN/ZH/TH using code keys."""
        available_langs = set(self.env["res.lang"].sudo().search([]).mapped("code"))
        translations = {
            "lab.department.type": {
                "chemistry": {"en_US": "Clinical Chemistry", "zh_CN": "临床化学", "th_TH": "เคมีคลินิก"},
                "general": {"en_US": "General", "zh_CN": "综合科", "th_TH": "ทั่วไป"},
                "hematology": {"en_US": "Hematology", "zh_CN": "血液学", "th_TH": "โลหิตวิทยา"},
                "microbiology": {"en_US": "Microbiology", "zh_CN": "微生物学", "th_TH": "จุลชีววิทยา"},
                "immunology": {"en_US": "Immunology", "zh_CN": "免疫学", "th_TH": "ภูมิคุ้มกันวิทยา"},
                "other": {"en_US": "Other", "zh_CN": "其他", "th_TH": "อื่นๆ"},
            },
            "lab.sample.type": {
                "blood": {"en_US": "Whole Blood", "zh_CN": "全血", "th_TH": "เลือดเต็มส่วน"},
                "urine": {"en_US": "Urine", "zh_CN": "尿液", "th_TH": "ปัสสาวะ"},
                "stool": {"en_US": "Stool", "zh_CN": "粪便", "th_TH": "อุจจาระ"},
                "swab": {"en_US": "Swab", "zh_CN": "拭子样本", "th_TH": "ตัวอย่างสวอบ"},
                "serum": {"en_US": "Serum", "zh_CN": "血清", "th_TH": "ซีรัม"},
                "other": {"en_US": "Other", "zh_CN": "其他", "th_TH": "อื่นๆ"},
            },
            "lab.priority.type": {
                "routine": {"en_US": "Routine", "zh_CN": "常规", "th_TH": "ปกติ"},
                "urgent": {"en_US": "Urgent", "zh_CN": "加急", "th_TH": "เร่งด่วน"},
                "stat": {"en_US": "STAT", "zh_CN": "急诊（STAT）", "th_TH": "ด่วนพิเศษ (STAT)"},
            },
            "lab.request.type": {
                "individual": {"en_US": "Individual", "zh_CN": "个人", "th_TH": "บุคคล"},
                "institution": {"en_US": "Institution", "zh_CN": "机构", "th_TH": "หน่วยงาน"},
            },
        }
        for model_name, codes in translations.items():
            model = self.env[model_name].sudo()
            for code, lang_map in codes.items():
                rec = model.search([("code", "=", code)], limit=1)
                if not rec:
                    continue
                for lang, value in lang_map.items():
                    if lang not in available_langs:
                        continue
                    rec.with_context(lang=lang).write({"name": value})
        return True


class LabDepartmentType(models.Model):
    _name = "lab.department.type"
    _description = "Laboratory Department Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("lab_department_type_code_uniq", "unique(code)", "Department code must be unique."),
    ]


class LabSampleType(models.Model):
    _name = "lab.sample.type"
    _description = "Laboratory Sample Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("lab_sample_type_code_uniq", "unique(code)", "Sample type code must be unique."),
    ]


class LabPriorityType(models.Model):
    _name = "lab.priority.type"
    _description = "Laboratory Priority Type"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("lab_priority_type_code_uniq", "unique(code)", "Priority code must be unique."),
    ]


class LabRequestType(models.Model):
    _name = "lab.request.type"
    _description = "Laboratory Request Type"
    _order = "sequence, id"
    _ALLOWED_CODES = {"individual", "institution"}
    _CONFIG_ONLY_FIELDS = {
        "allowed_service_ids",
        "exclude_selected_services",
        "allowed_profile_ids",
        "exclude_selected_profiles",
    }

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)
    allowed_service_ids = fields.Many2many(
        "lab.service",
        "lab_request_type_service_rel",
        "request_type_id",
        "service_id",
        string="Allowed Services",
        domain="[('active','=',True), ('company_id', '=', company_id), ('profile_only', '=', False)]",
    )
    exclude_selected_services = fields.Boolean(
        string="Exclude Selected Services",
        default=False,
        help="If enabled, selected services are excluded and all other services are allowed. "
        "If no services are selected, all services are allowed.",
    )
    allowed_profile_ids = fields.Many2many(
        "lab.profile",
        "lab_request_type_profile_rel",
        "request_type_id",
        "profile_id",
        string="Allowed Profiles",
        domain="[('active','=',True), ('company_id', '=', company_id)]",
    )
    exclude_selected_profiles = fields.Boolean(
        string="Exclude Selected Profiles",
        default=False,
        help="If enabled, selected profiles are excluded and all other profiles are allowed. "
        "If no panels are selected, all panels are allowed.",
    )
    allowed_service_count = fields.Integer(compute="_compute_allowed_counts", string="Allowed Service Count")
    allowed_profile_count = fields.Integer(compute="_compute_allowed_counts", string="Allowed Profile Count")

    _sql_constraints = [
        ("lab_request_type_code_uniq", "unique(code)", "Request type code must be unique."),
    ]

    def _is_system_write_context(self):
        return bool(
            self.env.context.get("install_mode")
            or self.env.context.get("module")
            or self.env.context.get("from_module")
            or self.env.is_superuser()
        )

    @api.constrains("code")
    def _check_builtin_code(self):
        for rec in self:
            if rec.code not in self._ALLOWED_CODES:
                raise ValidationError(_("Only built-in request types are allowed: individual, institution."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self._is_system_write_context():
            raise ValidationError(_("Request type records are fixed by system and cannot be created manually."))
        records = super().create(vals_list)
        for rec in records:
            if rec.code not in self._ALLOWED_CODES:
                raise ValidationError(_("Only built-in request types are allowed: individual, institution."))
        return records

    def write(self, vals):
        if self._is_system_write_context():
            return super().write(vals)
        invalid_fields = set(vals.keys()) - self._CONFIG_ONLY_FIELDS
        if invalid_fields:
            raise ValidationError(
                _("Only service/panel scope fields can be updated on request types.")
            )
        invalid_records = self.filtered(lambda rec: rec.code not in rec._ALLOWED_CODES)
        if invalid_records:
            raise ValidationError(_("Only built-in request types can be configured."))
        return super().write(vals)

    def unlink(self):
        if not self._is_system_write_context():
            raise ValidationError(_("Request type records are fixed by system and cannot be deleted."))
        return super().unlink()

    @api.constrains("allowed_service_ids", "allowed_profile_ids", "company_id")
    def _check_scope_company(self):
        for rec in self:
            if rec.allowed_service_ids.filtered(lambda s: s.company_id and s.company_id != rec.company_id):
                raise ValidationError(_("Allowed Services must belong to the same company as Request Type."))
            if rec.allowed_profile_ids.filtered(lambda p: p.company_id and p.company_id != rec.company_id):
                raise ValidationError(_("Allowed Profiles must belong to the same company as Request Type."))

    @api.depends(
        "allowed_service_ids",
        "allowed_profile_ids",
        "exclude_selected_services",
        "exclude_selected_profiles",
        "company_id",
    )
    def _compute_allowed_counts(self):
        service_model = self.env["lab.service"].sudo()
        profile_model = self.env["lab.profile"].sudo()
        for rec in self:
            service_domain = [
                ("active", "=", True),
                ("company_id", "=", rec.company_id.id),
                ("profile_only", "=", False),
            ]
            profile_domain = [
                ("active", "=", True),
                ("company_id", "=", rec.company_id.id),
            ]

            if rec.allowed_service_ids:
                if rec.exclude_selected_services:
                    service_domain.append(("id", "not in", rec.allowed_service_ids.ids))
                    rec.allowed_service_count = service_model.search_count(service_domain)
                else:
                    rec.allowed_service_count = len(
                        rec.allowed_service_ids.filtered(
                            lambda s: s.active and s.company_id == rec.company_id and not s.profile_only
                        )
                    )
            else:
                # Empty list means all are allowed.
                rec.allowed_service_count = service_model.search_count(service_domain)

            if rec.allowed_profile_ids:
                if rec.exclude_selected_profiles:
                    profile_domain.append(("id", "not in", rec.allowed_profile_ids.ids))
                    rec.allowed_profile_count = profile_model.search_count(profile_domain)
                else:
                    rec.allowed_profile_count = len(
                        rec.allowed_profile_ids.filtered(lambda p: p.active and p.company_id == rec.company_id)
                    )
            else:
                # Empty list means all are allowed.
                rec.allowed_profile_count = profile_model.search_count(profile_domain)
