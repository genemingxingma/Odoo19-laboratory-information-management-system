from odoo import api, fields, models


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
        return self._selection_from_master(
            "lab.request.type",
            [("individual", "Individual"), ("institution", "Institution")],
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

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    is_default = fields.Boolean(default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("lab_request_type_code_uniq", "unique(code)", "Request type code must be unique."),
    ]
