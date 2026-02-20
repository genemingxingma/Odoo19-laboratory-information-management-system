from odoo import fields, models


class LabReportTemplate(models.Model):
    _name = "lab.report.template"
    _description = "Laboratory Report Template"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    title = fields.Char(default="Laboratory Report")
    show_reference = fields.Boolean(default=True)
    show_flag = fields.Boolean(default=True)
    show_notes = fields.Boolean(default=True)
    show_ai_summary_in_pdf = fields.Boolean(
        string="Show AI Summary in PDF",
        default=True,
    )
    active = fields.Boolean(default=True)
    note = fields.Text()
    ai_interpretation_enabled = fields.Boolean(
        string="Enable AI Interpretation",
        default=True,
    )
    ai_auto_generate_on_release = fields.Boolean(
        string="Auto Generate on Report Release",
        default=True,
    )
    ai_system_prompt = fields.Text(
        string="AI System Prompt",
        default=(
            "You are a laboratory report interpretation assistant. "
            "Provide educational interpretation only, never diagnose."
        ),
    )
    ai_user_prompt_template = fields.Text(
        string="AI User Prompt Template",
        default=(
            "Sample: {sample_name}\n"
            "Patient: {patient_name}\n"
            "Client: {client_name}\n"
            "Physician: {physician_name}\n"
            "Template: {report_template}\n"
            "Priority: {priority}\n"
            "State: {state}\n"
            "Collection Date: {collection_date}\n"
            "Verified Date: {verified_date}\n"
            "Report Date: {report_date}\n"
            "Sample Note: {sample_note}\n"
            "Amendment Note: {amendment_note}\n"
            "\n"
            "Report Snapshot:\n{report_snapshot}\n"
            "\n"
            "Analysis Results:\n{analysis_lines}\n"
            "\n"
            "Abnormal Items:\n{abnormal_lines}\n"
            "\n"
            "Please provide a structured interpretation with sections:\n"
            "1) Key findings\n"
            "2) Abnormal items and potential significance\n"
            "3) Clinical caution and limitations\n"
            "4) Recommended follow-up actions\n"
            "Keep concise and factual. Output language: {output_language}."
        ),
    )
    ai_temperature = fields.Float(
        string="AI Temperature",
        default=0.2,
    )
