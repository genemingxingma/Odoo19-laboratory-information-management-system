from odoo import api, fields, models


class LabTestRequestCompany(models.Model):
    _inherit = "lab.test.request"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
        return super().create(vals_list)


class LabTestRequestLineCompany(models.Model):
    _inherit = "lab.test.request.line"

    company_id = fields.Many2one(related="request_id.company_id", store=True, readonly=True, index=True)


class LabTestRequestQuoteRevisionCompany(models.Model):
    _inherit = "lab.test.request.quote.revision"

    company_id = fields.Many2one(related="request_id.company_id", store=True, readonly=True, index=True)


class LabTestRequestTimelineCompany(models.Model):
    _inherit = "lab.test.request.timeline"

    company_id = fields.Many2one(related="request_id.company_id", store=True, readonly=True, index=True)


class LabSampleCompany(models.Model):
    _inherit = "lab.sample"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
        return super().create(vals_list)


class LabSampleAnalysisCompany(models.Model):
    _inherit = "lab.sample.analysis"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabSampleAmendmentCompany(models.Model):
    _inherit = "lab.sample.amendment"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabSampleTimelineCompany(models.Model):
    _inherit = "lab.sample.timeline"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabSampleSignoffCompany(models.Model):
    _inherit = "lab.sample.signoff"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabSampleCustodyCompany(models.Model):
    _inherit = "lab.sample.custody"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabReportDispatchCompany(models.Model):
    _inherit = "lab.report.dispatch"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabReportDispatchLogCompany(models.Model):
    _inherit = "lab.report.dispatch.log"

    company_id = fields.Many2one(related="dispatch_id.company_id", store=True, readonly=True, index=True)


class LabReportAckSignatureCompany(models.Model):
    _inherit = "lab.report.ack.signature"

    company_id = fields.Many2one(related="sample_id.company_id", store=True, readonly=True, index=True)


class LabRequestInvoiceCompany(models.Model):
    _inherit = "lab.request.invoice"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
        return super().create(vals_list)


class LabRequestInvoiceLineCompany(models.Model):
    _inherit = "lab.request.invoice.line"

    company_id = fields.Many2one(related="invoice_id.company_id", store=True, readonly=True, index=True)


class LabRequestPaymentCompany(models.Model):
    _inherit = "lab.request.payment"

    company_id = fields.Many2one(related="invoice_id.company_id", store=True, readonly=True, index=True)


class LabRequestRefundCompany(models.Model):
    _inherit = "lab.request.refund"

    company_id = fields.Many2one(related="invoice_id.company_id", store=True, readonly=True, index=True)


class LabBillingReconciliationCompany(models.Model):
    _inherit = "lab.billing.reconciliation"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("company_id", self.env.company.id)
        return super().create(vals_list)


class LabBillingReconciliationLineCompany(models.Model):
    _inherit = "lab.billing.reconciliation.line"

    company_id = fields.Many2one(related="report_id.company_id", store=True, readonly=True, index=True)


class LabServiceCompany(models.Model):
    _inherit = "lab.service"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabProfileCompany(models.Model):
    _inherit = "lab.profile"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabReportTemplateCompany(models.Model):
    _inherit = "lab.report.template"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabReportEmailTemplateCompany(models.Model):
    _inherit = "lab.report.email.template"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabDepartmentTypeCompany(models.Model):
    _inherit = "lab.department.type"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabSampleTypeCompany(models.Model):
    _inherit = "lab.sample.type"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabPriorityTypeCompany(models.Model):
    _inherit = "lab.priority.type"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabRequestTypeCompany(models.Model):
    _inherit = "lab.request.type"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class LabResultUnitCompany(models.Model):
    _inherit = "lab.result.unit"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
