import html
import re
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


def _extract_menu_xmlids(module_dir):
    menu_names = {}
    for view_path in (Path(module_dir) / "views").glob("*.xml"):
        text = view_path.read_text(encoding="utf-8")
        for match in re.finditer(r"<menuitem\s+([^>]+)>?", text):
            attrs = match.group(1)
            menu_id = re.search(r'id="([^"]+)"', attrs)
            menu_name = re.search(r'name="([^"]+)"', attrs)
            if menu_id and menu_name:
                xmlid = f"laboratory_management.{menu_id.group(1)}"
                menu_names[xmlid] = html.unescape(menu_name.group(1))
    return menu_names


def sync_menu_i18n(env):
    module_dir = Path(__file__).resolve().parent
    menu_names = _extract_menu_xmlids(module_dir)
    zh_terms = _parse_po(module_dir / "i18n" / "zh_CN.po")
    th_terms = _parse_po(module_dir / "i18n" / "th_TH.po")

    for xmlid, source_name in menu_names.items():
        menu = env.ref(xmlid, raise_if_not_found=False)
        if not menu:
            continue
        zh_name = zh_terms.get(source_name)
        th_name = th_terms.get(source_name)
        if zh_name:
            menu.with_context(lang="zh_CN").name = zh_name
        if th_name:
            menu.with_context(lang="th_TH").name = th_name


def post_init_hook(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    sync_menu_i18n(env)

