from odoo import api, fields, models


class LabImportJob(models.Model):
    _name = "lab.import.job"
    _description = "Laboratory Import Job"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, copy=False, readonly=True, default="New", tracking=True)
    import_type = fields.Selection(
        [
            ("manual_csv", "Manual CSV Result Import"),
            ("instrument_csv", "Instrument CSV Result Import"),
        ],
        required=True,
        tracking=True,
    )
    file_name = fields.Char()
    started_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    finished_at = fields.Datetime(readonly=True)
    status = fields.Selection(
        [("running", "Running"), ("done", "Done"), ("failed", "Failed")],
        default="running",
        tracking=True,
    )
    total_rows = fields.Integer(default=0)
    success_rows = fields.Integer(default=0)
    failed_rows = fields.Integer(default=0)
    note = fields.Text()
    line_ids = fields.One2many("lab.import.job.line", "job_id", string="Import Lines", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.import.job") or "New"
        return super().create(vals_list)


class LabImportJobLine(models.Model):
    _name = "lab.import.job.line"
    _description = "Laboratory Import Job Line"
    _order = "id"

    job_id = fields.Many2one("lab.import.job", required=True, ondelete="cascade")
    row_no = fields.Integer(required=True)
    accession = fields.Char()
    instrument_code = fields.Char()
    test_code = fields.Char()
    service_code = fields.Char()
    result_value = fields.Char()
    status = fields.Selection([( "success", "Success"), ("failed", "Failed")], required=True)
    message = fields.Char()
