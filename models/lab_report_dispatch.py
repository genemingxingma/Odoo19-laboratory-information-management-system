import hashlib
import json
import secrets

from odoo import _, api, fields, models


class LabReportDispatch(models.Model):
    _name = "lab.report.dispatch"
    _description = "Lab Report Dispatch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(default="New", readonly=True, copy=False, tracking=True)
    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True, tracking=True)
    partner_id = fields.Many2one("res.partner", required=True, index=True, tracking=True)
    channel = fields.Selection(
        [
            ("portal", "Portal"),
            ("email", "Email"),
            ("manual", "Manual"),
        ],
        default="portal",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Sent"),
            ("viewed", "Viewed"),
            ("downloaded", "Downloaded"),
            ("acknowledged", "Acknowledged"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    token = fields.Char(default=lambda self: secrets.token_urlsafe(20), copy=False, readonly=True, index=True)

    sent_at = fields.Datetime(readonly=True, tracking=True)
    viewed_at = fields.Datetime(readonly=True, tracking=True)
    downloaded_at = fields.Datetime(readonly=True, tracking=True)
    acknowledged_at = fields.Datetime(readonly=True, tracking=True)

    reminder_count = fields.Integer(default=0, readonly=True, tracking=True)
    last_reminder_at = fields.Datetime(readonly=True, tracking=True)

    acknowledged_by_name = fields.Char(readonly=True)
    acknowledged_note = fields.Text()

    log_ids = fields.One2many("lab.report.dispatch.log", "dispatch_id", string="Dispatch Logs", readonly=True)
    log_count = fields.Integer(compute="_compute_log_count")
    signature_ids = fields.One2many("lab.report.ack.signature", "dispatch_id", string="Ack Signatures", readonly=True)
    signature_count = fields.Integer(compute="_compute_signature_count")

    def _compute_log_count(self):
        for rec in self:
            rec.log_count = len(rec.log_ids)

    def _compute_signature_count(self):
        for rec in self:
            rec.signature_count = len(rec.signature_ids)

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = seq.next_by_code("lab.report.dispatch") or "New"
            if not vals.get("token"):
                vals["token"] = secrets.token_urlsafe(20)
        records = super().create(vals_list)
        for rec in records:
            rec._log_event("create", _("Dispatch created."))
        return records

    def _log_event(self, event_type, message, extra=None):
        now = fields.Datetime.now()
        vals_list = []
        for rec in self:
            vals_list.append(
                {
                    "dispatch_id": rec.id,
                    "event_type": event_type,
                    "message": message,
                    "user_id": self.env.user.id,
                    "event_time": now,
                    "extra": extra or False,
                }
            )
        if vals_list:
            self.env["lab.report.dispatch.log"].sudo().create(vals_list)

    def action_mark_sent(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == "cancel":
                continue
            rec.write(
                {
                    "state": "sent",
                    "sent_at": now,
                }
            )
            rec._log_event("sent", _("Report dispatch marked as sent."))
            rec.message_post(body=_("Report sent to %s.") % (rec.partner_id.name,))
        return True

    def action_mark_viewed(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("acknowledged", "cancel"):
                continue
            vals = {
                "state": "viewed",
                "viewed_at": now,
            }
            if rec.state == "draft" and not rec.sent_at:
                vals["sent_at"] = now
            rec.write(vals)
            rec._log_event("viewed", _("Report viewed by recipient."))
        return True

    def action_mark_downloaded(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("acknowledged", "cancel"):
                continue
            vals = {"downloaded_at": now}
            if rec.state in ("draft", "sent", "viewed", "downloaded"):
                vals["state"] = "downloaded"
            if rec.state == "draft" and not rec.sent_at:
                vals["sent_at"] = now
            rec.write(vals)
            rec._log_event("downloaded", _("Report downloaded by recipient."))
        return True

    def action_acknowledge(self, signer_name=None, note=None):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state == "cancel":
                continue
            rec.write(
                {
                    "state": "acknowledged",
                    "acknowledged_at": now,
                    "acknowledged_by_name": signer_name or rec.partner_id.name,
                    "acknowledged_note": note or rec.acknowledged_note,
                }
            )
            rec._log_event("acknowledged", _("Report acknowledged by recipient."), extra=note)
            rec.message_post(body=_("Report acknowledged by %s.") % (rec.acknowledged_by_name,))
        return True

    def action_view_signatures(self):
        self.ensure_one()
        action = self.env.ref("laboratory_management.action_lab_report_ack_signature").sudo().read()[0]
        action["domain"] = [("dispatch_id", "=", self.id)]
        action["context"] = {
            "default_dispatch_id": self.id,
            "default_sample_id": self.sample_id.id,
            "default_partner_id": self.partner_id.id,
        }
        return action

    def create_portal_signature(self, signer_name, note, consent, ip_addr, user_agent, partner):
        self.ensure_one()
        if self.state == "cancel":
            return False
        payload = {
            "dispatch": self.name,
            "sample": self.sample_id.name,
            "partner": partner.id if partner else False,
            "signer_name": signer_name,
            "consent": bool(consent),
            "signed_at": fields.Datetime.now().isoformat(),
            "ip": ip_addr or "",
            "ua": user_agent or "",
            "note": note or "",
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.env["lab.report.ack.signature"].sudo().create(
            {
                "sample_id": self.sample_id.id,
                "dispatch_id": self.id,
                "partner_id": partner.id if partner else False,
                "user_id": self.env.user.id,
                "signer_name": signer_name,
                "consent": bool(consent),
                "sign_note": note or False,
                "ip_address": ip_addr or False,
                "user_agent": user_agent or False,
                "payload_json": raw,
                "signature_hash": digest,
                "signed_at": fields.Datetime.now(),
            }
        )

    def action_cancel_dispatch(self):
        for rec in self:
            rec.write({"state": "cancel"})
            rec._log_event("cancel", _("Dispatch cancelled."))
        return True

    def action_reset_dispatch(self):
        for rec in self:
            rec.write(
                {
                    "state": "draft",
                    "sent_at": False,
                    "viewed_at": False,
                    "downloaded_at": False,
                    "acknowledged_at": False,
                    "acknowledged_by_name": False,
                    "acknowledged_note": False,
                }
            )
            rec._log_event("reset", _("Dispatch reset to draft."))
        return True

    def action_send_reminder(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.state in ("acknowledged", "cancel"):
                continue
            rec.write(
                {
                    "reminder_count": rec.reminder_count + 1,
                    "last_reminder_at": now,
                }
            )
            rec._log_event("reminder", _("Acknowledgement reminder issued."))
            rec.message_post(body=_("Reminder sent to %s.") % (rec.partner_id.name,))
        return True

    @api.model
    def _cron_dispatch_ack_reminder(self):
        cfg = self.env["ir.config_parameter"].sudo()
        enabled = (cfg.get_param("laboratory_management.dispatch_ack_reminder_enabled") or "1").strip()
        if enabled in ("0", "false", "False"):
            return

        min_hours = int((cfg.get_param("laboratory_management.dispatch_ack_reminder_hours") or "24").strip())
        max_batch = int((cfg.get_param("laboratory_management.dispatch_ack_reminder_limit") or "50").strip())

        threshold = fields.Datetime.subtract(fields.Datetime.now(), hours=min_hours)
        records = self.search(
            [
                ("state", "in", ("sent", "viewed", "downloaded")),
                "|",
                ("last_reminder_at", "=", False),
                ("last_reminder_at", "<", threshold),
            ],
            order="sent_at asc, id asc",
            limit=max_batch,
        )
        records.action_send_reminder()

    @api.model
    def portal_find_dispatch_for_partner(self, sample, partner):
        return self.search(
            [
                ("sample_id", "=", sample.id),
                ("partner_id", "child_of", partner.commercial_partner_id.id),
                ("state", "!=", "cancel"),
            ],
            order="id desc",
            limit=1,
        )


class LabReportDispatchLog(models.Model):
    _name = "lab.report.dispatch.log"
    _description = "Lab Report Dispatch Log"
    _order = "id desc"

    dispatch_id = fields.Many2one("lab.report.dispatch", required=True, ondelete="cascade", index=True)
    event_type = fields.Selection(
        [
            ("create", "Create"),
            ("sent", "Sent"),
            ("viewed", "Viewed"),
            ("downloaded", "Downloaded"),
            ("acknowledged", "Acknowledged"),
            ("reminder", "Reminder"),
            ("cancel", "Cancelled"),
            ("reset", "Reset"),
        ],
        required=True,
        index=True,
    )
    event_time = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    user_id = fields.Many2one("res.users", index=True)
    message = fields.Char(required=True)
    extra = fields.Text()


class LabReportAckSignature(models.Model):
    _name = "lab.report.ack.signature"
    _description = "Lab Report Acknowledgement Signature"
    _order = "id desc"

    sample_id = fields.Many2one("lab.sample", required=True, ondelete="cascade", index=True)
    dispatch_id = fields.Many2one("lab.report.dispatch", required=True, ondelete="cascade", index=True)
    partner_id = fields.Many2one("res.partner", index=True)
    user_id = fields.Many2one("res.users", index=True)

    signer_name = fields.Char(required=True)
    consent = fields.Boolean(default=False, required=True)
    sign_note = fields.Text()

    signed_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    ip_address = fields.Char()
    user_agent = fields.Char()

    payload_json = fields.Text(readonly=True)
    signature_hash = fields.Char(required=True, readonly=True, index=True)
