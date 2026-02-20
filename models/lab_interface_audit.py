import json

from odoo import api, fields, models


class LabInterfaceAuditLog(models.Model):
    _name = "lab.interface.audit.log"
    _description = "Interface Audit Log"
    _order = "id desc"

    endpoint_id = fields.Many2one("lab.interface.endpoint", index=True, ondelete="set null")
    job_id = fields.Many2one("lab.interface.job", index=True, ondelete="set null")
    action = fields.Selection(
        [
            ("ingest", "Ingest"),
            ("process", "Process"),
            ("requeue", "Requeue"),
            ("ack", "Ack"),
            ("error", "Error"),
        ],
        required=True,
    )
    direction = fields.Selection([("inbound", "Inbound"), ("outbound", "Outbound")], required=True)
    external_uid = fields.Char(index=True)
    source_ip = fields.Char()
    payload = fields.Text()
    result = fields.Text()
    state = fields.Char()
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    event_at = fields.Datetime(default=fields.Datetime.now, required=True)

    @api.model
    def log_event(self, *, action, direction, endpoint=False, job=False, external_uid=False, source_ip=False, payload=False, result=False, state=False):
        payload_text = payload if isinstance(payload, str) else json.dumps(payload or {}, ensure_ascii=False, indent=2)
        result_text = result if isinstance(result, str) else json.dumps(result or {}, ensure_ascii=False, indent=2)
        return self.create(
            {
                "action": action,
                "direction": direction,
                "endpoint_id": endpoint.id if endpoint else False,
                "job_id": job.id if job else False,
                "external_uid": external_uid or False,
                "source_ip": source_ip or False,
                "payload": payload_text,
                "result": result_text,
                "state": state or "",
            }
        )
