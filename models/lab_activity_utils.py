from odoo import models


class LabActivityHelperMixin(models.AbstractModel):
    _name = "lab.activity.helper.mixin"
    _description = "Activity Helper Mixin"

    def create_unique_todo_activities(self, *, model_name, entries):
        """Create TODO activities without duplicates by (res_id, user_id, summary)."""
        if not entries:
            return 0

        todo = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not todo:
            return 0

        model_id = self.env["ir.model"]._get_id(model_name)
        res_ids = sorted({int(e["res_id"]) for e in entries if e.get("res_id")})
        user_ids = sorted({int(e["user_id"]) for e in entries if e.get("user_id")})
        summaries = sorted({e.get("summary") for e in entries if e.get("summary")})
        if not res_ids or not user_ids or not summaries:
            return 0

        existing = self.env["mail.activity"].search(
            [
                ("res_model_id", "=", model_id),
                ("res_id", "in", res_ids),
                ("user_id", "in", user_ids),
                ("summary", "in", summaries),
            ]
        )
        existing_keys = {(x.res_id, x.user_id.id, x.summary) for x in existing}

        vals_list = []
        for entry in entries:
            res_id = int(entry.get("res_id") or 0)
            user_id = int(entry.get("user_id") or 0)
            summary = entry.get("summary") or ""
            if not (res_id and user_id and summary):
                continue
            key = (res_id, user_id, summary)
            if key in existing_keys:
                continue
            existing_keys.add(key)
            vals_list.append(
                {
                    "activity_type_id": todo.id,
                    "res_model_id": model_id,
                    "res_id": res_id,
                    "user_id": user_id,
                    "summary": summary,
                    "note": entry.get("note") or "",
                }
            )
        if not vals_list:
            return 0
        self.env["mail.activity"].create(vals_list)
        return len(vals_list)
