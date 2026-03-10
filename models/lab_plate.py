import base64
import csv
import io
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LabPlateBatch(models.Model):
    _name = "lab.plate.batch"
    _description = "Laboratory Plate Batch"
    _inherit = ["mail.thread", "mail.activity.mixin", "lab.master.data.mixin"]
    _order = "id desc"

    name = fields.Char(string="Plate Batch No.", default="New", readonly=True, copy=False, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    department = fields.Selection(selection="_selection_department", default=lambda self: self._default_department_code(), required=True, tracking=True)
    service_id = fields.Many2one("lab.service", string="Target Service", domain="[('active','=',True), ('company_id','=',company_id)]", tracking=True)
    plate_format = fields.Selection([("96", "96-well"), ("384", "384-well")], default="96", required=True, tracking=True)
    state = fields.Selection(
        [("draft", "Draft"), ("loaded", "Loaded"), ("in_progress", "In Progress"), ("done", "Done"), ("cancelled", "Cancelled")],
        default="draft",
        tracking=True,
        index=True,
    )
    worksheet_id = fields.Many2one("lab.worksheet", string="Worksheet", readonly=True)
    note = fields.Text()

    line_ids = fields.One2many("lab.plate.batch.line", "batch_id", string="Well Lines", copy=False)
    total_wells = fields.Integer(compute="_compute_counts")
    assigned_wells = fields.Integer(compute="_compute_counts")
    remaining_wells = fields.Integer(compute="_compute_counts")

    scan_payload = fields.Text(
        string="Scan/Paste Barcodes",
        help="One accession/accession barcode per line. System assigns in current empty-well order.",
    )
    plate_grid_html = fields.Html(
        string="Plate Grid",
        compute="_compute_plate_grid_html",
        sanitize=False,
    )

    @api.depends("line_ids", "line_ids.analysis_id")
    def _compute_counts(self):
        for rec in self:
            rec.total_wells = len(rec.line_ids)
            rec.assigned_wells = len(rec.line_ids.filtered("analysis_id"))
            rec.remaining_wells = rec.total_wells - rec.assigned_wells

    @api.depends("line_ids", "line_ids.analysis_id", "line_ids.analysis_state", "plate_format")
    def _compute_plate_grid_html(self):
        for rec in self:
            if rec.plate_format == "384":
                rows = [chr(c) for c in range(ord("A"), ord("P") + 1)]
                cols = list(range(1, 25))
            else:
                rows = [chr(c) for c in range(ord("A"), ord("H") + 1)]
                cols = list(range(1, 13))

            line_map = {line.well_code: line for line in rec.line_ids}
            html_parts = [
                "<div style='overflow:auto'>",
                "<table class='table table-sm table-bordered' style='min-width:720px; table-layout:fixed;'>",
                "<thead><tr><th style='width:56px;'>Row</th>",
            ]
            for col in cols:
                html_parts.append(f"<th style='text-align:center'>{col}</th>")
            html_parts.append("</tr></thead><tbody>")

            for row in rows:
                html_parts.append(f"<tr><th style='text-align:center'>{row}</th>")
                for col in cols:
                    code = f"{row}{col}"
                    line = line_map.get(code)
                    if not line or not line.analysis_id:
                        bg = "#f3f4f6"
                        label = code
                        title = f"{code}: empty"
                    else:
                        state = line.analysis_state or "assigned"
                        if state == "verified":
                            bg = "#d1fae5"
                        elif state == "done":
                            bg = "#fde68a"
                        elif state == "rejected":
                            bg = "#fecaca"
                        else:
                            bg = "#bfdbfe"
                        label = f"{code}<br/><small>{escape(line.sample_accession or '-')}</small>"
                        title = f"{code}: {escape(line.sample_accession or '-')}, {escape(state)}"
                    href = f"/web#id={line.id}&model=lab.plate.batch.line&view_type=form" if line else "#"
                    html_parts.append(
                        "<td style='padding:0;'>"
                        f"<a href='{href}' title='{title}' style='display:block; min-height:42px; text-align:center; background:{bg}; "
                        "text-decoration:none; color:#111827; padding:4px;'>"
                        f"{label}</a></td>"
                    )
                html_parts.append("</tr>")

            html_parts.append("</tbody></table></div>")
            rec.plate_grid_html = "".join(html_parts)

    @api.model_create_multi
    def create(self, vals_list):
        seq_model = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq_model.next_by_code("lab.plate.batch") or "New"
        records = super().create(vals_list)
        for rec in records:
            rec._ensure_well_lines()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "plate_format" in vals:
            for rec in self:
                if rec.state != "draft":
                    continue
                rec.action_reset_wells()
        return res

    def _well_codes(self):
        self.ensure_one()
        if self.plate_format == "384":
            rows = [chr(c) for c in range(ord("A"), ord("P") + 1)]
            cols = list(range(1, 25))
        else:
            rows = [chr(c) for c in range(ord("A"), ord("H") + 1)]
            cols = list(range(1, 13))
        seq = 1
        for r in rows:
            for c in cols:
                yield seq, r, c, f"{r}{c}"
                seq += 1

    def _ensure_well_lines(self):
        for rec in self:
            if rec.line_ids:
                continue
            vals_list = []
            for seq, row, col, code in rec._well_codes():
                vals_list.append(
                    {
                        "batch_id": rec.id,
                        "sequence": seq,
                        "row_code": row,
                        "column_no": col,
                        "well_code": code,
                        "company_id": rec.company_id.id,
                    }
                )
            self.env["lab.plate.batch.line"].create(vals_list)

    def action_reset_wells(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft plate batches can reset wells."))
            rec.line_ids._unassign_analysis_links()
            rec.line_ids.unlink()
            rec._ensure_well_lines()

    def _pending_analysis_domain(self):
        self.ensure_one()
        domain = [
            ("state", "in", ("pending", "assigned")),
            ("plate_batch_id", "=", False),
            ("department", "=", self.department),
            ("company_id", "=", self.company_id.id),
        ]
        if self.service_id:
            domain.append(("service_id", "=", self.service_id.id))
        return domain

    def action_auto_assign_pending(self):
        for rec in self:
            rec._ensure_well_lines()
            empty_lines = rec.line_ids.filtered(lambda x: not x.analysis_id).sorted("sequence")
            if not empty_lines:
                raise UserError(_("No empty wells in this plate."))
            analyses = self.env["lab.sample.analysis"].search(rec._pending_analysis_domain(), order="id asc", limit=len(empty_lines))
            if not analyses:
                raise UserError(_("No pending analyses available for this plate criteria."))
            for line, analysis in zip(empty_lines, analyses):
                line.assign_analysis(analysis)
            rec.state = "loaded"

    def action_apply_scan_payload(self):
        for rec in self:
            rec._ensure_well_lines()
            codes = [x.strip() for x in (rec.scan_payload or "").splitlines() if x.strip()]
            if not codes:
                raise UserError(_("Please paste at least one accession/barcode line."))
            empty_lines = rec.line_ids.filtered(lambda x: not x.analysis_id).sorted("sequence")
            if not empty_lines:
                raise UserError(_("No empty wells in this plate."))
            assigned = 0
            for code in codes:
                if assigned >= len(empty_lines):
                    break
                sample = self.env["lab.sample"].search(["|", ("name", "=", code), ("accession_barcode", "=", code)], limit=1)
                if not sample:
                    continue
                domain = rec._pending_analysis_domain() + [("sample_id", "=", sample.id)]
                analysis = self.env["lab.sample.analysis"].search(domain, order="id asc", limit=1)
                if not analysis:
                    continue
                empty_lines[assigned].assign_analysis(analysis)
                assigned += 1
            if assigned == 0:
                raise UserError(_("No analyzable records matched pasted barcodes."))
            rec.state = "loaded"

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_done(self):
        for rec in self:
            pending = rec.line_ids.filtered(lambda x: x.analysis_id and x.analysis_id.state not in ("done", "verified"))
            if pending:
                raise UserError(_("Some assigned wells are not completed yet."))
            rec.state = "done"

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_create_worksheet(self):
        for rec in self:
            assigned_analyses = rec.line_ids.filtered("analysis_id").mapped("analysis_id").sorted(lambda a: (a.plate_well_order or 9999, a.id))
            if not assigned_analyses:
                raise UserError(_("No assigned analyses in plate."))
            if rec.worksheet_id:
                worksheet = rec.worksheet_id
            else:
                worksheet = self.env["lab.worksheet"].create(
                    {
                        "department": rec.department,
                        "planned_date": fields.Datetime.now(),
                        "note": _("Auto-generated from plate batch %s") % (rec.name,),
                    }
                )
                rec.worksheet_id = worksheet.id
            assigned_analyses.write({"worksheet_id": worksheet.id, "state": "assigned"})
            return {
                "type": "ir.actions.act_window",
                "res_model": "lab.worksheet",
                "view_mode": "form",
                "res_id": worksheet.id,
                "target": "current",
            }

    def action_export_instrument_csv(self):
        self.ensure_one()
        lines = self.line_ids.sorted("sequence")
        if not lines:
            raise UserError(_("No well lines found for export."))

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Well Position",
                "Accession",
                "Accession Barcode",
                "Sample ID",
                "Service Code",
                "Service Name",
                "Analysis ID",
                "Analysis State",
                "Result Value",
            ]
        )
        for line in lines:
            analysis = line.analysis_id
            writer.writerow(
                [
                    line.well_code or "",
                    line.sample_accession or "",
                    line.accession_barcode or "",
                    analysis.sample_id.id if analysis and analysis.sample_id else "",
                    analysis.service_id.code if analysis and analysis.service_id else "",
                    analysis.service_id.name if analysis and analysis.service_id else "",
                    analysis.id if analysis else "",
                    line.analysis_state or "",
                    analysis.result_value if analysis else "",
                ]
            )

        datas = base64.b64encode(output.getvalue().encode("utf-8"))
        filename = f"{self.name or 'plate_batch'}_instrument_template.csv"
        attachment = self.env["ir.attachment"].sudo().create(
            {
                "name": filename,
                "type": "binary",
                "datas": datas,
                "res_model": self._name,
                "res_id": self.id,
                "mimetype": "text/csv",
                "company_id": self.company_id.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=1",
            "target": "self",
        }


class LabPlateBatchLine(models.Model):
    _name = "lab.plate.batch.line"
    _description = "Plate Batch Well Line"
    _order = "sequence, id"

    batch_id = fields.Many2one("lab.plate.batch", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", related="batch_id.company_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    row_code = fields.Char(required=True)
    column_no = fields.Integer(required=True)
    well_code = fields.Char(required=True, index=True)

    analysis_id = fields.Many2one("lab.sample.analysis", string="Assigned Analysis", ondelete="set null", index=True)
    sample_id = fields.Many2one(related="analysis_id.sample_id", store=True, readonly=True)
    service_id = fields.Many2one(related="analysis_id.service_id", store=True, readonly=True)
    sample_accession = fields.Char(related="analysis_id.sample_id.name", string="Accession", store=True, readonly=True)
    accession_barcode = fields.Char(related="analysis_id.sample_id.accession_barcode", string="Accession Barcode", store=True, readonly=True)
    analysis_state = fields.Selection(related="analysis_id.state", string="Analysis State", store=True, readonly=True)

    _sql_constraints = [
        ("lab_plate_line_batch_well_uniq", "unique(batch_id, well_code)", "Well code must be unique in one plate batch."),
    ]

    @api.constrains("analysis_id")
    def _check_analysis_unique_in_batch(self):
        for rec in self:
            if not rec.analysis_id:
                continue
            dup = self.search_count(
                [
                    ("batch_id", "=", rec.batch_id.id),
                    ("analysis_id", "=", rec.analysis_id.id),
                    ("id", "!=", rec.id),
                ]
            )
            if dup:
                raise ValidationError(_("Same analysis cannot occupy multiple wells in one plate."))

    def assign_analysis(self, analysis):
        self.ensure_one()
        if not analysis:
            return
        if analysis.plate_batch_id and analysis.plate_batch_id != self.batch_id:
            raise UserError(
                _("Analysis %(analysis)s is already assigned to plate %(plate)s.")
                % {"analysis": analysis.display_name, "plate": analysis.plate_batch_id.display_name}
            )
        self.write({"analysis_id": analysis.id})

    def _unassign_analysis_links(self):
        analyses = self.mapped("analysis_id")
        if analyses:
            analyses.write({"plate_batch_id": False, "plate_well_position": False, "plate_well_order": 0})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_analysis_plate_fields()
        return records

    def write(self, vals):
        old_analyses = self.mapped("analysis_id")
        res = super().write(vals)
        self._sync_analysis_plate_fields()
        (old_analyses - self.mapped("analysis_id")).write({"plate_batch_id": False, "plate_well_position": False, "plate_well_order": 0})
        return res

    def unlink(self):
        analyses = self.mapped("analysis_id")
        res = super().unlink()
        if analyses:
            analyses.write({"plate_batch_id": False, "plate_well_position": False, "plate_well_order": 0})
        return res

    def _sync_analysis_plate_fields(self):
        for rec in self:
            if rec.analysis_id:
                rec.analysis_id.write(
                    {
                        "plate_batch_id": rec.batch_id.id,
                        "plate_well_position": rec.well_code,
                        "plate_well_order": rec.sequence,
                    }
                )


class LabSampleAnalysisPlateMixin(models.Model):
    _inherit = "lab.sample.analysis"

    plate_batch_id = fields.Many2one("lab.plate.batch", string="Plate Batch", index=True)
    plate_well_position = fields.Char(string="Well Position", index=True)
    plate_well_order = fields.Integer(string="Well Order", index=True)
