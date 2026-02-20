import base64
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class LabInstrumentResultImportWizard(models.TransientModel):
    _name = "lab.instrument.result.import.wizard"
    _description = "Instrument Result Import Wizard"

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
        required_cols = {"accession", "instrument_code", "test_code", "result"}
        if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
            raise UserError(_("CSV columns required: accession, instrument_code, test_code, result, remark(optional)."))

        job = self.env["lab.import.job"].create(
            {
                "import_type": "instrument_csv",
                "file_name": self.file_name,
                "status": "running",
                "note": _("Instrument CSV import started."),
            }
        )

        updated = 0
        failed = 0
        total = 0

        for row_no, row in enumerate(reader, start=2):
            total += 1
            accession = (row.get("accession") or "").strip()
            instrument_code = (row.get("instrument_code") or "").strip()
            test_code = (row.get("test_code") or "").strip()
            result = (row.get("result") or "").strip()
            remark = (row.get("remark") or "").strip()

            status = "success"
            message = "Imported"
            service_code = ""

            try:
                if not accession or not instrument_code or not test_code:
                    raise UserError(_("Missing accession, instrument_code, or test_code"))

                instrument = self.env["lab.instrument"].search([("code", "=", instrument_code)], limit=1)
                if not instrument:
                    raise UserError(_("Instrument not found"))

                mapping = self.env["lab.instrument.test.map"].search(
                    [
                        ("instrument_id", "=", instrument.id),
                        ("instrument_test_code", "=", test_code),
                    ],
                    limit=1,
                )
                if not mapping:
                    raise UserError(_("Mapping not found"))

                service_code = mapping.service_id.code
                sample = self.env["lab.sample"].search(
                    ["|", ("name", "=", accession), ("accession_barcode", "=", accession)],
                    limit=1,
                )
                if not sample:
                    raise UserError(_("Sample not found"))

                analysis = self.env["lab.sample.analysis"].search(
                    [
                        ("sample_id", "=", sample.id),
                        ("service_id", "=", mapping.service_id.id),
                        ("state", "in", ("pending", "assigned", "done", "rejected")),
                    ],
                    order="id desc",
                    limit=1,
                )
                if not analysis:
                    raise UserError(_("Analysis line not found for mapped service"))

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
                    "instrument_code": instrument_code,
                    "test_code": test_code,
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
                "note": _("Instrument CSV import finished."),
            }
        )

        msg = _("Instrument import completed. Success: %(u)s, Failed: %(f)s") % {"u": updated, "f": failed}
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Instrument Import"),
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
