from odoo import _, api, fields, models


class LabGovernanceEvidence(models.Model):
    _name = "lab.governance.evidence"
    _description = "Laboratory Governance Evidence"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "evidence_date desc, id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    title = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    evidence_type = fields.Selection(
        [
            ("document", "Controlled Document"),
            ("approval", "Approval"),
            ("signature", "Electronic Signature"),
            ("training", "Training Evidence"),
            ("validation", "Validation Evidence"),
            ("attachment", "Attachment Evidence"),
            ("other", "Other"),
        ],
        default="attachment",
        required=True,
        tracking=True,
    )
    evidence_date = fields.Datetime(default=fields.Datetime.now, required=True, tracking=True)
    reference = fields.Char(tracking=True)
    summary = fields.Text()
    source_model = fields.Char(required=True, index=True)
    source_res_id = fields.Integer(required=True, index=True)
    source_display_name = fields.Char(compute="_compute_source_display_name")
    approval_record_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Approval Record",
    )
    controlled_document_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Controlled Document",
    )
    signature_record_ref = fields.Reference(
        selection="_selection_governance_reference_models",
        string="Signature Record",
    )

    change_control_id = fields.Many2one("lab.change.control", string="Change Control", index=True)
    risk_register_id = fields.Many2one("lab.risk.register", string="Risk Register", index=True)
    nonconformance_id = fields.Many2one("lab.nonconformance", string="Nonconformance / CAPA", index=True)
    method_validation_id = fields.Many2one("lab.method.validation", string="Method Validation", index=True)
    training_id = fields.Many2one("lab.quality.training", string="Training", index=True)

    attachment_count = fields.Integer(compute="_compute_attachment_count")

    _name_uniq = models.Constraint("unique(name)", "Governance evidence number must be unique.")

    @api.model
    def _selection_governance_reference_models(self):
        labels = {
            "documents.document": _("Document"),
            "knowledge.article": _("Knowledge Article"),
            "approval.request": _("Approval Request"),
            "sign.request": _("Sign Request"),
            "ir.attachment": _("Attachment"),
        }
        return [(model_name, label) for model_name, label in labels.items() if model_name in self.env]

    @api.depends("source_model", "source_res_id")
    def _compute_source_display_name(self):
        for rec in self:
            name = False
            if rec.source_model and rec.source_res_id and rec.source_model in self.env:
                source = self.env[rec.source_model].browse(rec.source_res_id)
                if source.exists():
                    name = source.display_name
            rec.source_display_name = name or ("%s,%s" % (rec.source_model or "-", rec.source_res_id or 0))

    def _compute_attachment_count(self):
        att_obj = self.env["ir.attachment"].sudo()
        for rec in self:
            rec.attachment_count = att_obj.search_count([("res_model", "=", rec._name), ("res_id", "=", rec.id)])

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.governance.evidence") or "New"
        return super().create(vals_list)

    def action_view_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Evidence Attachments"),
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": [("res_model", "=", self._name), ("res_id", "=", self.id)],
            "context": {"default_res_model": self._name, "default_res_id": self.id},
        }

    @api.model
    def _normalize_reference_for_evidence(self, record_ref):
        if not record_ref:
            return False, False
        if isinstance(record_ref, models.BaseModel):
            return record_ref._name, record_ref.id
        if isinstance(record_ref, str) and "," in record_ref:
            model_name, res_id = record_ref.split(",", 1)
            try:
                return model_name, int(res_id)
            except ValueError:
                return False, False
        return False, False

    @api.model
    def create_or_update_for_source(
        self,
        *,
        source_record,
        evidence_type,
        title,
        reference=False,
        summary=False,
        approval_record_ref=False,
        controlled_document_ref=False,
        signature_record_ref=False,
        extra_vals=None,
    ):
        source_record.ensure_one()
        domain = [
            ("source_model", "=", source_record._name),
            ("source_res_id", "=", source_record.id),
            ("evidence_type", "=", evidence_type),
            ("title", "=", title),
        ]
        if reference:
            domain.append(("reference", "=", reference))
        evidence = self.search(domain, limit=1)
        vals = {
            "title": title,
            "company_id": getattr(source_record, "company_id", self.env.company).id if getattr(source_record, "company_id", False) else self.env.company.id,
            "source_model": source_record._name,
            "source_res_id": source_record.id,
            "evidence_type": evidence_type,
            "reference": reference or False,
            "summary": summary or False,
            "approval_record_ref": approval_record_ref or False,
            "controlled_document_ref": controlled_document_ref or False,
            "signature_record_ref": signature_record_ref or False,
        }
        if extra_vals:
            vals.update(extra_vals)
        if evidence:
            evidence.write(vals)
            return evidence
        return self.create(vals)


class LabGovernanceEvidenceMixin(models.AbstractModel):
    _name = "lab.governance.evidence.mixin"
    _description = "Laboratory Governance Evidence Mixin"

    evidence_count = fields.Integer(compute="_compute_governance_evidence_count")

    def _governance_source_model_name(self):
        return self._name

    def _compute_governance_evidence_count(self):
        evidence_obj = self.env["lab.governance.evidence"].sudo()
        model_name = self._governance_source_model_name()
        grouped = evidence_obj.read_group(
            [("source_model", "=", model_name), ("source_res_id", "in", self.ids)],
            ["source_res_id"],
            ["source_res_id"],
        )
        count_map = {
            item["source_res_id"]: item["source_res_id_count"]
            for item in grouped
            if item.get("source_res_id")
        }
        for rec in self:
            rec.evidence_count = count_map.get(rec.id, 0)

    def _governance_default_evidence_vals(self):
        self.ensure_one()
        return {
            "title": self.display_name,
            "company_id": getattr(self, "company_id", self.env.company).id if getattr(self, "company_id", False) else self.env.company.id,
            "source_model": self._name,
            "source_res_id": self.id,
        }

    def action_view_governance_evidence(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_governance_evidence").sudo().read()[0]
        action["domain"] = [("source_model", "=", self._name), ("source_res_id", "=", self.id)]
        action["context"] = {
            "default_source_model": self._name,
            "default_source_res_id": self.id,
            **self._governance_default_evidence_vals(),
        }
        return action

    def _ensure_governance_evidence(
        self,
        *,
        evidence_type,
        title,
        reference=False,
        summary=False,
        approval_record_ref=False,
        controlled_document_ref=False,
        signature_record_ref=False,
        extra_vals=None,
    ):
        self.ensure_one()
        return self.env["lab.governance.evidence"].sudo().create_or_update_for_source(
            source_record=self,
            evidence_type=evidence_type,
            title=title,
            reference=reference,
            summary=summary,
            approval_record_ref=approval_record_ref,
            controlled_document_ref=controlled_document_ref,
            signature_record_ref=signature_record_ref,
            extra_vals=extra_vals,
        )
