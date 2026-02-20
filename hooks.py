from pathlib import Path

from odoo import SUPERUSER_ID, api


def _parse_po(msg_file):
    terms = {}
    lines = Path(msg_file).read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("msgid "):
            msgid = lines[i][6:].strip().strip('"')
            i += 1
            while i < len(lines) and lines[i].startswith('"'):
                msgid += lines[i].strip().strip('"')
                i += 1
            msgstr = ""
            if i < len(lines) and lines[i].startswith("msgstr "):
                msgstr = lines[i][7:].strip().strip('"')
                i += 1
                while i < len(lines) and lines[i].startswith('"'):
                    msgstr += lines[i].strip().strip('"')
                    i += 1
            if msgid and msgstr:
                terms[msgid] = msgstr
            continue
        i += 1
    return terms


def sync_menu_i18n(env):
    module_dir = Path(__file__).resolve().parent
    zh_terms = _parse_po(module_dir / "i18n" / "zh_CN.po")
    th_terms = _parse_po(module_dir / "i18n" / "th_TH.po")
    menu_ids = env["ir.model.data"].search(
        [("module", "=", "laboratory_management"), ("model", "=", "ir.ui.menu")]
    ).mapped("res_id")
    if not menu_ids:
        return

    cr = env.cr
    for source_name, zh_name in zh_terms.items():
        cr.execute(
            """
            UPDATE ir_ui_menu
               SET name = jsonb_set(coalesce(name, '{}'::jsonb), '{zh_CN}', to_jsonb(%s::text), true),
                   write_date = now()
             WHERE id = ANY(%s)
               AND name->>'en_US' = %s
            """,
            [zh_name, menu_ids, source_name],
        )
    for source_name, th_name in th_terms.items():
        cr.execute(
            """
            UPDATE ir_ui_menu
               SET name = jsonb_set(coalesce(name, '{}'::jsonb), '{th_TH}', to_jsonb(%s::text), true),
                   write_date = now()
             WHERE id = ANY(%s)
               AND name->>'en_US' = %s
            """,
            [th_name, menu_ids, source_name],
        )


def sync_field_i18n(env):
    module_dir = Path(__file__).resolve().parent
    zh_terms = _parse_po(module_dir / "i18n" / "zh_CN.po")
    th_terms = _parse_po(module_dir / "i18n" / "th_TH.po")
    cr = env.cr
    for source_name, zh_name in zh_terms.items():
        cr.execute(
            """
            UPDATE ir_model_fields
               SET field_description = jsonb_set(coalesce(field_description, '{}'::jsonb), '{zh_CN}', to_jsonb(%s::text), true),
                   write_date = now()
             WHERE model LIKE 'lab.%%'
               AND field_description->>'en_US' = %s
            """,
            [zh_name, source_name],
        )
    for source_name, th_name in th_terms.items():
        cr.execute(
            """
            UPDATE ir_model_fields
               SET field_description = jsonb_set(coalesce(field_description, '{}'::jsonb), '{th_TH}', to_jsonb(%s::text), true),
                   write_date = now()
             WHERE model LIKE 'lab.%%'
               AND field_description->>'en_US' = %s
            """,
            [th_name, source_name],
        )


def sync_i18n_terms(env):
    sync_menu_i18n(env)
    sync_field_i18n(env)


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sync_i18n_terms(env)
