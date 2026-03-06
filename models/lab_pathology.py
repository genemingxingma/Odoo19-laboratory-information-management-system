import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LabPathologyCase(models.Model):
    _name = "lab.pathology.case"
    _description = "Pathology Case"
    _inherit = ["mail.thread", "mail.activity.mixin", "portal.mixin", "lab.master.data.mixin"]
    _order = "id desc"

    name = fields.Char(string="Case No.", default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    sample_id = fields.Many2one("lab.sample", string="Source Sample", required=True, index=True, tracking=True)
    request_id = fields.Many2one(related="sample_id.request_id", string="Request", store=True, readonly=True)
    patient_id = fields.Many2one(related="sample_id.patient_id", string="Patient", store=True, readonly=True)
    client_id = fields.Many2one(related="sample_id.client_id", string="Client/Institution", store=True, readonly=True)
    physician_name = fields.Char(related="sample_id.physician_name", string="Physician", store=True, readonly=True)
    accession_barcode = fields.Char(related="sample_id.accession_barcode", string="Accession Barcode", store=True, readonly=True)

    priority = fields.Selection(selection="_selection_priority", default=lambda self: self._default_priority_code(), required=True, tracking=True)
    pathology_type = fields.Selection(
        [
            ("histopathology", "Histopathology"),
            ("cytopathology", "Cytopathology"),
            ("molecular_pathology", "Molecular Pathology"),
            ("hematopathology", "Hematopathology"),
            ("other", "Other"),
        ],
        string="Pathology Type",
        default="histopathology",
        required=True,
        tracking=True,
    )
    diagnosis_category = fields.Selection(
        [
            ("negative", "Negative/Benign"),
            ("atypical", "Atypical"),
            ("suspicious", "Suspicious"),
            ("malignant", "Malignant"),
            ("indeterminate", "Indeterminate"),
        ],
        string="Diagnosis Category",
        default="indeterminate",
        tracking=True,
    )
    icd_o_code = fields.Char(string="ICD-O Code")
    tnm_stage = fields.Char(string="TNM Stage")
    tumor_grade = fields.Selection(
        [
            ("g1", "Grade 1"),
            ("g2", "Grade 2"),
            ("g3", "Grade 3"),
            ("g4", "Grade 4"),
            ("na", "Not Applicable"),
        ],
        string="Tumor Grade",
        default="na",
    )
    specimen_received_at = fields.Datetime(string="Specimen Received At", tracking=True)
    gross_examined_at = fields.Datetime(string="Gross Examined At", tracking=True)
    microscopic_examined_at = fields.Datetime(string="Microscopic Examined At", tracking=True)
    diagnosis_at = fields.Datetime(string="Diagnosis Finalized At", tracking=True)
    reviewed_at = fields.Datetime(string="Reviewed At", tracking=True)
    reported_at = fields.Datetime(string="Reported At", tracking=True)

    clinical_history = fields.Html(string="Clinical History")
    gross_description = fields.Html(string="Gross Description")
    microscopic_description = fields.Html(string="Microscopic Description")
    final_diagnosis = fields.Html(string="Final Diagnosis")
    interpretation_comment = fields.Html(string="Interpretation Comment")
    recommendation = fields.Text(string="Recommendation")
    synoptic_summary = fields.Text(string="Synoptic Summary", compute="_compute_synoptic_summary")

    reviewed_by_id = fields.Many2one("res.users", string="Reviewed By", readonly=True, tracking=True)
    signed_by_id = fields.Many2one("res.users", string="Signed By", readonly=True, tracking=True)

    report_template_id = fields.Many2one(
        "lab.report.template",
        string="Report Template",
        default=lambda self: self.env.ref("laboratory_management.report_template_clinical", raise_if_not_found=False),
    )
    report_pdf_attachment_id = fields.Many2one("ir.attachment", string="Cached Report PDF", readonly=True, copy=False)
    report_pdf_cached_at = fields.Datetime(string="Report PDF Cached At", readonly=True, copy=False)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("accessioned", "Accessioned"),
            ("grossing", "Grossing"),
            ("microscopy", "Microscopy"),
            ("diagnosed", "Diagnosed"),
            ("reviewed", "Reviewed"),
            ("reported", "Reported"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        tracking=True,
        index=True,
    )

    specimen_ids = fields.One2many("lab.pathology.specimen", "case_id", string="Specimens")
    image_ids = fields.One2many("lab.pathology.image", "case_id", string="Images")
    slide_count = fields.Integer(compute="_compute_counts")
    specimen_count = fields.Integer(compute="_compute_counts")
    image_count = fields.Integer(compute="_compute_counts")
    ready_for_signoff = fields.Boolean(compute="_compute_ready_for_signoff")

    _sample_uniq = models.Constraint("unique(sample_id)", "Each sample can only have one pathology case.")

    def _compute_counts(self):
        for rec in self:
            rec.specimen_count = len(rec.specimen_ids)
            rec.slide_count = len(rec.specimen_ids.mapped("slide_ids"))
            rec.image_count = len(rec.image_ids)

    @api.depends("final_diagnosis", "specimen_ids", "specimen_ids.slide_ids")
    def _compute_ready_for_signoff(self):
        for rec in self:
            rec.ready_for_signoff = bool((rec.final_diagnosis or "").strip() and rec.specimen_count > 0 and rec.slide_count > 0)

    @api.depends("pathology_type", "diagnosis_category", "icd_o_code", "tnm_stage", "tumor_grade", "recommendation")
    def _compute_synoptic_summary(self):
        pathology_labels = dict(self._fields["pathology_type"].selection)
        category_labels = dict(self._fields["diagnosis_category"].selection)
        grade_labels = dict(self._fields["tumor_grade"].selection)
        for rec in self:
            parts = [
                _("Type: %s") % pathology_labels.get(rec.pathology_type or "", "-"),
                _("Category: %s") % category_labels.get(rec.diagnosis_category or "", "-"),
                _("ICD-O: %s") % (rec.icd_o_code or "-"),
                _("TNM: %s") % (rec.tnm_stage or "-"),
                _("Grade: %s") % grade_labels.get(rec.tumor_grade or "", "-"),
            ]
            if rec.recommendation:
                parts.append(_("Recommendation: %s") % rec.recommendation)
            rec.synoptic_summary = "\n".join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.pathology.case") or "New"
            if not vals.get("report_template_id"):
                default_template = self.env.ref("laboratory_management.report_template_clinical", raise_if_not_found=False)
                if default_template:
                    vals["report_template_id"] = default_template.id
        records = super().create(vals_list)
        for rec in records:
            rec.sample_id.pathology_case_id = rec.id
            rec.message_post(body=_("Pathology case created from sample %s.") % (rec.sample_id.name,))
        return records

    def action_set_accessioned(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.write({"state": "accessioned", "specimen_received_at": rec.specimen_received_at or now})

    def action_set_grossing(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("cancelled", "reported"):
                continue
            rec.write({"state": "grossing", "gross_examined_at": rec.gross_examined_at or now})

    def action_set_microscopy(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("cancelled", "reported"):
                continue
            rec.write({"state": "microscopy", "microscopic_examined_at": rec.microscopic_examined_at or now})

    def action_set_diagnosed(self):
        now = fields.Datetime.now()
        for rec in self:
            if not (rec.final_diagnosis or "").strip():
                raise UserError(_("Final diagnosis is required before marking Diagnosed."))
            rec.write({"state": "diagnosed", "diagnosis_at": rec.diagnosis_at or now})

    def action_set_reviewed(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state != "diagnosed":
                raise UserError(_("Only diagnosed cases can be reviewed."))
            rec.write({"state": "reviewed", "reviewed_at": now, "reviewed_by_id": self.env.user.id})

    def action_release_report(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state not in ("diagnosed", "reviewed"):
                raise UserError(_("Case must be diagnosed/reviewed before releasing report."))
            if not (rec.final_diagnosis or "").strip():
                raise UserError(_("Final diagnosis is required before releasing report."))
            if not rec.specimen_ids:
                raise UserError(_("At least one pathology specimen is required before releasing report."))
            if not rec.specimen_ids.mapped("slide_ids"):
                raise UserError(_("At least one pathology slide is required before releasing report."))
            rec.write({"state": "reported", "reported_at": now, "signed_by_id": self.env.user.id})
            rec._generate_report_pdf_attachment(force=True, suppress_error=False)

    def action_cancel(self):
        for rec in self:
            rec.state = "cancelled"

    def action_reset_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_print_report(self):
        self.ensure_one()
        return self.env.ref("laboratory_management.action_report_lab_pathology_case").report_action(self)

    def action_view_specimens(self):
        self.ensure_one()
        return {
            "name": _("Pathology Specimens"),
            "type": "ir.actions.act_window",
            "res_model": "lab.pathology.specimen",
            "view_mode": "list,form",
            "domain": [("case_id", "=", self.id)],
            "context": {"default_case_id": self.id, "default_company_id": self.company_id.id},
        }

    def action_view_images(self):
        self.ensure_one()
        return {
            "name": _("Pathology Images"),
            "type": "ir.actions.act_window",
            "res_model": "lab.pathology.image",
            "view_mode": "kanban,list,form",
            "domain": [("case_id", "=", self.id)],
            "context": {"default_case_id": self.id, "default_company_id": self.company_id.id},
        }

    def _get_report_action(self):
        self.ensure_one()
        return self.env.ref("laboratory_management.action_report_lab_pathology_case", raise_if_not_found=False)

    def _generate_report_pdf_attachment(self, force=False, suppress_error=False):
        self.ensure_one()
        if self.report_pdf_attachment_id and not force:
            return self.report_pdf_attachment_id
        action = self._get_report_action()
        if not action:
            if suppress_error:
                return self.env["ir.attachment"]
            raise UserError(_("Pathology PDF report action is missing."))
        try:
            pdf_content, _fmt = action._render_qweb_pdf(action.report_name, res_ids=self.ids)
            datas = base64.b64encode(pdf_content or b"")
            vals = {
                "name": "%s - Pathology Report.pdf" % (self.name or "Pathology"),
                "type": "binary",
                "datas": datas,
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "application/pdf",
                "company_id": self.company_id.id,
            }
            attachment = self.report_pdf_attachment_id.sudo()
            if attachment:
                attachment.write(vals)
            else:
                attachment = self.env["ir.attachment"].sudo().create(vals)
            self.sudo().write({"report_pdf_attachment_id": attachment.id, "report_pdf_cached_at": fields.Datetime.now()})
            return attachment
        except Exception:
            if suppress_error:
                return self.env["ir.attachment"]
            raise


class LabPathologySpecimen(models.Model):
    _name = "lab.pathology.specimen"
    _description = "Pathology Specimen"
    _inherit = ["lab.master.data.mixin"]
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Specimen No.", default="New", readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    case_id = fields.Many2one("lab.pathology.case", required=True, ondelete="cascade", index=True)
    sample_id = fields.Many2one(related="case_id.sample_id", store=True, readonly=True)
    specimen_type = fields.Selection(selection="_selection_sample_type", default=lambda self: self._default_sample_type_code(), required=True)
    specimen_site = fields.Char(string="Specimen Site")
    container_no = fields.Char(string="Container ID")
    fixative = fields.Char(string="Fixative")
    collected_at = fields.Datetime(string="Collected At")
    received_at = fields.Datetime(string="Received At")
    gross_note = fields.Html(string="Gross Note")
    cassette_count = fields.Integer(string="Cassette Count", default=0)

    slide_ids = fields.One2many("lab.pathology.slide", "specimen_id", string="Slides")
    image_ids = fields.One2many("lab.pathology.image", "specimen_id", string="Images")

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.pathology.specimen") or "New"
        return super().create(vals_list)


class LabPathologySlide(models.Model):
    _name = "lab.pathology.slide"
    _description = "Pathology Slide"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Slide ID", default="New", readonly=True, copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    case_id = fields.Many2one(related="specimen_id.case_id", store=True, readonly=True)
    specimen_id = fields.Many2one("lab.pathology.specimen", required=True, ondelete="cascade", index=True)
    block_id = fields.Char(string="Block ID")
    stain_method = fields.Char(string="Stain Method")
    stain_result = fields.Char(string="Stain Result")
    microscopic_note = fields.Html(string="Microscopic Note")
    state = fields.Selection(
        [("draft", "Draft"), ("prepared", "Prepared"), ("reviewed", "Reviewed")],
        default="draft",
        required=True,
    )

    image_ids = fields.One2many("lab.pathology.image", "slide_id", string="Images")

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.pathology.slide") or "New"
        return super().create(vals_list)


class LabPathologyImage(models.Model):
    _name = "lab.pathology.image"
    _description = "Pathology Image"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    case_id = fields.Many2one("lab.pathology.case", required=True, ondelete="cascade", index=True)
    specimen_id = fields.Many2one("lab.pathology.specimen", ondelete="set null", index=True)
    slide_id = fields.Many2one("lab.pathology.slide", ondelete="set null", index=True)
    image_1920 = fields.Image(string="Image", max_width=4096, max_height=4096, attachment=True, required=True)
    capture_datetime = fields.Datetime(string="Captured At")
    magnification = fields.Char(string="Magnification")
    note = fields.Text()

    @api.constrains("specimen_id", "slide_id", "case_id")
    def _check_case_consistency(self):
        for rec in self:
            if rec.specimen_id and rec.specimen_id.case_id != rec.case_id:
                raise UserError(_("Specimen does not belong to the selected pathology case."))
            if rec.slide_id and rec.slide_id.case_id != rec.case_id:
                raise UserError(_("Slide does not belong to the selected pathology case."))


class LabSamplePathologyMixin(models.Model):
    _inherit = "lab.sample"

    pathology_case_id = fields.Many2one("lab.pathology.case", string="Pathology Case", copy=False, readonly=True, index=True)
    pathology_case_count = fields.Integer(compute="_compute_pathology_case_count")

    def _compute_pathology_case_count(self):
        for rec in self:
            rec.pathology_case_count = 1 if rec.pathology_case_id else 0

    def action_create_pathology_case(self):
        self.ensure_one()
        if self.pathology_case_id:
            return self.action_view_pathology_case()
        case = self.env["lab.pathology.case"].create(
            {
                "sample_id": self.id,
                "company_id": self.company_id.id,
                "priority": self.priority,
                "clinical_history": self.note or "",
            }
        )
        self.pathology_case_id = case.id
        return case.action_view_form()

    def action_view_pathology_case(self):
        self.ensure_one()
        if not self.pathology_case_id:
            raise UserError(_("No pathology case is linked to this sample."))
        return self.pathology_case_id.action_view_form()


class LabPathologyCaseActionMixin(models.Model):
    _inherit = "lab.pathology.case"

    def action_view_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Pathology Case"),
            "res_model": "lab.pathology.case",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }
