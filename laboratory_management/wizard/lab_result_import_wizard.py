import base64
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class LabResultImportWizard(models.TransientModel):
    _name = "lab.result.import.wizard"
    _description = "Lab Result Import Wizard"

    file_data = fields.Binary(required=True)
    file_name = fields.Char()
    delimiter = fields.Selection(
        [(",", "Comma (,)"), (";", "Semicolon (;)"), ("\t", "Tab")],
        default=",",
        required=True,
    )
    auto_mark_done = fields.Boolean(default=True)

    def action_import(self):
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Please upload a CSV file."))

        content = base64.b64decode(self.file_data)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UserError(_("CSV must be UTF-8 encoded.")) from exc

        reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
        required_cols = {"accession", "service_code", "result"}
        if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
            raise UserError(_("CSV columns required: accession, service_code, result, remark(optional)."))

        job = self.env["lab.import.job"].create(
            {
                "import_type": "manual_csv",
                "file_name": self.file_name,
                "status": "running",
                "note": _("Manual CSV import started."),
            }
        )

        updated = 0
        failed = 0
        total = 0

        for row_no, row in enumerate(reader, start=2):
            total += 1
            accession = (row.get("accession") or "").strip()
            service_code = (row.get("service_code") or "").strip().upper()
            result = (row.get("result") or "").strip()
            remark = (row.get("remark") or "").strip()

            status = "success"
            message = "Imported"

            try:
                if not accession or not service_code:
                    raise UserError(_("Missing accession or service_code"))

                sample = self.env["lab.sample"].search(
                    ["|", ("name", "=", accession), ("accession_barcode", "=", accession)],
                    limit=1,
                )
                if not sample:
                    raise UserError(_("Sample not found"))

                analysis = self.env["lab.sample.analysis"].search(
                    [
                        ("sample_id", "=", sample.id),
                        ("service_id.code", "=", service_code),
                        ("state", "in", ("pending", "assigned", "done", "rejected")),
                    ],
                    limit=1,
                    order="id desc",
                )
                if not analysis:
                    raise UserError(_("Analysis line not found for service code"))

                analysis.write({"result_value": result, "result_note": remark})
                if self.auto_mark_done and analysis.state in ("pending", "assigned", "rejected"):
                    analysis.action_mark_done()
                updated += 1
            except Exception as err:  # noqa: BLE001
                status = "failed"
                message = str(err)
                failed += 1

            self.env["lab.import.job.line"].create(
                {
                    "job_id": job.id,
                    "row_no": row_no,
                    "accession": accession,
                    "service_code": service_code,
                    "result_value": result,
                    "status": status,
                    "message": message[:255],
                }
            )

        job.write(
            {
                "status": "done" if failed == 0 else "failed",
                "total_rows": total,
                "success_rows": updated,
                "failed_rows": failed,
                "finished_at": fields.Datetime.now(),
                "note": _("Manual CSV import finished."),
            }
        )

        msg = _("Import completed. Success: %(u)s, Failed: %(f)s") % {"u": updated, "f": failed}
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Result Import"),
                "message": msg,
                "type": "success" if failed == 0 else "warning",
                "sticky": False,
                "next": {
                    "type": "ir.actions.act_window",
                    "res_model": "lab.import.job",
                    "res_id": job.id,
                    "view_mode": "form",
                    "target": "current",
                },
            },
        }
