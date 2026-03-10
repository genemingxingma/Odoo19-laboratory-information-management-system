# Odoo shell script: full LIS demo setup for local learning
# Usage:
#   /Users/mingxingmac/Documents/Codex/.local/venv-odoo19/bin/python \
#   /Users/mingxingmac/Documents/Codex/.local/odoo19/odoo-bin shell \
#   -c /Users/mingxingmac/Documents/Codex/.local/odoo19.conf -d odoo19_dev \
#   < /Users/mingxingmac/Documents/Codex/Odoo19-laboratory-information-management-system/scripts/setup_full_demo_local.py

from odoo import fields

summary = []
company = env.company
now = fields.Datetime.now()


def log(msg):
    summary.append(msg)


def ensure_by_code(model, code, vals, company_field=True):
    domain = [("code", "=", code)]
    if company_field and "company_id" in env[model]._fields:
        domain.append(("company_id", "=", company.id))
    rec = env[model].sudo().search(domain, limit=1)
    data = dict(vals)
    data.setdefault("code", code)
    if company_field and "company_id" in env[model]._fields:
        data.setdefault("company_id", company.id)
    if rec:
        rec.write(data)
    else:
        rec = env[model].sudo().create(data)
    return rec


def ensure_portal_user(login, name, password, partner):
    portal_group = env.ref("base.group_portal")
    user = env["res.users"].sudo().search([("login", "=", login)], limit=1)
    vals = {
        "name": name,
        "login": login,
        "partner_id": partner.id,
        "active": True,
        "password": password,
        "group_ids": [(6, 0, [portal_group.id])],
    }
    if user:
        user.write(vals)
    else:
        user = env["res.users"].sudo().with_context(no_reset_password=True).create(vals)
    return user


# 1) Master data + language seed
env["lab.master.data.mixin"].seed_i18n_master_data()
log("Master data i18n seeded")

# 2) Core master data extension (sample types / units)
for code, name in [
    ("cervical_swab", "Cervical Swab"),
    ("urethral_swab", "Urethral Swab"),
    ("vaginal_swab", "Vaginal Swab"),
    ("ffpe", "FFPE Tissue"),
    ("cytology_smear", "Cytology Smear"),
]:
    ensure_by_code("lab.sample.type", code, {"name": name, "sequence": 80, "active": True})

for code, name in [
    ("ct", "Ct"),
    ("copies_ml", "copies/mL"),
    ("gray", "gray_value"),
    ("index", "index"),
]:
    ensure_by_code("lab.result.unit", code, {"name": name, "sequence": 20, "active": True})
log("Sample types and units ensured")

# 3) Institution / contacts / physicians
partner_model = env["res.partner"].sudo()
physician_dept = ensure_by_code("lab.physician.department", "GYN", {"name": "Gynecology", "sequence": 10, "active": True})
physician_dept_path = ensure_by_code("lab.physician.department", "PATH", {"name": "Pathology", "sequence": 20, "active": True})

institution = partner_model.search([("name", "=", "Demo Medical Center"), ("is_company", "=", True)], limit=1)
if not institution:
    institution = partner_model.create({"name": "Demo Medical Center", "is_company": True, "company_type": "company"})

physician_model = env["lab.physician"].sudo()
for code, name, dept in [
    ("DR-DEMO-GYN-01", "Dr. Alice Gyn", physician_dept),
    ("DR-DEMO-PATH-01", "Dr. Bob Path", physician_dept_path),
]:
    doc = physician_model.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "company_id": company.id,
        "lab_physician_department_id": dept.id,
        "institution_partner_id": institution.id,
        "email": code.lower() + "@demo.local",
        "active": True,
    }
    if doc:
        doc.write(vals)
    else:
        physician_model.create(vals)
log("Institution and physicians ensured")

# 4) Portal demo users
portal01_partner = partner_model.search([("email", "=", "portal-01@imytest.local")], limit=1)
if not portal01_partner:
    portal01_partner = partner_model.create({"name": "Portal 01", "email": "portal-01@imytest.local", "phone": "13900000001"})

portal_inst_partner = partner_model.search([("email", "=", "portal-inst-01@imytest.local")], limit=1)
if not portal_inst_partner:
    portal_inst_partner = partner_model.create(
        {
            "name": "Institution Portal 01",
            "email": "portal-inst-01@imytest.local",
            "parent_id": institution.id,
        }
    )

ensure_portal_user("portal-01@imytest.local", "portal-01", "Portal@12345", portal01_partner)
ensure_portal_user("portal-inst-01@imytest.local", "portal-inst-01", "Portal@12345", portal_inst_partner)
log("Portal users ensured")

# 5) Services catalog (Chemistry / HPV14 / STD7 / Pathology)
service_model = env["lab.service"].sudo()
unit_ct = env["lab.result.unit"].sudo().search([("code", "=", "ct"), ("company_id", "=", company.id)], limit=1)
unit_gray = env["lab.result.unit"].sudo().search([("code", "=", "gray"), ("company_id", "=", company.id)], limit=1)
unit_index = env["lab.result.unit"].sudo().search([("code", "=", "index"), ("company_id", "=", company.id)], limit=1)

# Chemistry
chem_services = []
for code, name, rng in [
    ("GLU-FAST", "Fasting Glucose", (3.9, 6.1)),
    ("ALT-SER", "Alanine Aminotransferase", (0.0, 40.0)),
]:
    svc = service_model.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "department": "chemistry",
        "sample_type": "serum",
        "result_type": "numeric",
        "unit_id": unit_index.id if unit_index else False,
        "ref_min": rng[0],
        "ref_max": rng[1],
        "critical_min": rng[0],
        "critical_max": rng[1] * 2,
        "auto_verify_enabled": True,
        "turnaround_hours": 8,
        "list_price": 39.0,
        "active": True,
    }
    if svc:
        svc.write(vals)
    else:
        svc = service_model.create(vals)
    chem_services.append(svc)

# HPV14
hpv_types = ["16", "18", "31", "33", "35", "39", "45", "51", "52", "56", "58", "59", "66", "68"]
hpv_services = env["lab.service"]
for t in hpv_types:
    code = f"HPV-{t}-GV"
    name = f"HPV {t} Genotyping Gray Value"
    svc = service_model.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "department": "microbiology",
        "sample_type": "cervical_swab",
        "result_type": "numeric",
        "unit_id": unit_gray.id if unit_gray else False,
        "ref_min": 0.0,
        "ref_max": 999999.0,
        "critical_min": 0.0,
        "critical_max": 999999.0,
        "auto_binary_enabled": True,
        "auto_binary_cutoff": 0.0,
        "auto_binary_negative_when_gte": False,  # >0 positive, <=0 negative
        "require_reagent_lot": True,
        "turnaround_hours": 24,
        "list_price": 88.0,
        "active": True,
    }
    if svc:
        svc.write(vals)
    else:
        svc = service_model.create(vals)
    hpv_services |= svc

# STD7
std_defs = [
    ("CT", "Chlamydia trachomatis"),
    ("UU", "Ureaplasma urealyticum"),
    ("NG", "Neisseria gonorrhoeae"),
    ("HSV1", "HSV-I"),
    ("HSV2", "HSV-II"),
    ("CAN", "Candida albicans"),
    ("GV", "Gardnerella vaginalis"),
]
std_services = env["lab.service"]
for short, display in std_defs:
    code = f"STD-{short}-CT"
    name = f"{display} PCR Ct"
    svc = service_model.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "department": "microbiology",
        "sample_type": "swab",
        "result_type": "numeric",
        "unit_id": unit_ct.id if unit_ct else False,
        "ref_min": 0.0,
        "ref_max": 45.0,
        "critical_min": 0.0,
        "critical_max": 45.0,
        "auto_binary_enabled": True,
        "auto_binary_cutoff": 33.0,
        "auto_binary_negative_when_gte": True,
        "require_reagent_lot": True,
        "turnaround_hours": 24,
        "list_price": 99.0,
        "active": True,
    }
    if svc:
        svc.write(vals)
    else:
        svc = service_model.create(vals)
    std_services |= svc

# Pathology text service
path_svc = service_model.search([("code", "=", "PATH-HISTO-DX"), ("company_id", "=", company.id)], limit=1)
path_vals = {
    "name": "Histopathology Diagnosis",
    "code": "PATH-HISTO-DX",
    "department": "other",
    "sample_type": "ffpe",
    "result_type": "text",
    "turnaround_hours": 72,
    "list_price": 299.0,
    "active": True,
}
if path_svc:
    path_svc.write(path_vals)
else:
    path_svc = service_model.create(path_vals)

log(f"Services ensured: chemistry={len(chem_services)}, hpv14={len(hpv_services)}, std7={len(std_services)}, pathology=1")

# 6) Panels / packages
profile_model = env["lab.profile"].sudo()
profile_line_model = env["lab.profile.line"].sudo()


def ensure_profile(code, name, services):
    prof = profile_model.search([("code", "=", code), ("company_id", "=", company.id)], limit=1)
    vals = {"name": name, "code": code, "active": True, "company_id": company.id}
    if prof:
        prof.write(vals)
    else:
        prof = profile_model.create(vals)
    prof.line_ids.unlink()
    for svc in services:
        profile_line_model.create({"profile_id": prof.id, "service_id": svc.id})
    return prof

hpv14_profile = ensure_profile("HPV14-PANEL", "HPV14 Genotyping Panel", hpv_services.sorted("code"))
std7_profile = ensure_profile("STD7-PANEL", "STD 7 Multiplex PCR Panel", std_services.sorted("code"))
std6_profile = ensure_profile("STD6-PANEL", "STD 6 Multiplex PCR Panel", std_services.sorted("code")[:6])
std4_profile = ensure_profile("STD4-PANEL", "STD 4 Multiplex PCR Panel", std_services.sorted("code")[:4])
std3_profile = ensure_profile("STD3-PANEL", "STD 3 Multiplex PCR Panel", std_services.sorted("code")[:3])
path_profile = ensure_profile("PATH-BASIC", "Pathology Basic Panel", path_svc)

log("Profiles ensured: HPV14 + STD3/4/6/7 + Pathology")

# 7) Interpretation profiles
interp_model = env["lab.interpretation.profile"].sudo()
interp_line_model = env["lab.interpretation.profile.line"].sudo()


def ensure_interp(code, name, services, eval_mode="binary_positive", pos_tpl="Positive ({detected} detected)", neg="Negative"):
    ip = interp_model.search([("code", "=", code)], limit=1)
    vals = {
        "name": name,
        "code": code,
        "service_match_mode": "all_required",
        "minimum_required_count": 1,
        "positive_summary_template": pos_tpl,
        "negative_summary_text": neg,
        "inconclusive_summary_text": "Inconclusive",
    }
    if ip:
        ip.write(vals)
    else:
        ip = interp_model.create(vals)
    existing = {l.service_id.id: l for l in ip.line_ids}
    for svc in services:
        lvals = {
            "profile_id": ip.id,
            "service_id": svc.id,
            "label": svc.name,
            "evaluation_mode": eval_mode,
            "include_in_detected": True,
            "active": True,
        }
        if eval_mode.startswith("numeric"):
            lvals["threshold_float"] = 0.0
        if svc.id in existing:
            existing[svc.id].write(lvals)
        else:
            interp_line_model.create(lvals)
    return ip

ensure_interp("HPV14-INTERP", "HPV14 Interpretation", hpv_services, eval_mode="binary_positive", pos_tpl="HPV Positive ({detected})")
ensure_interp("STD7-INTERP", "STD7 Interpretation", std_services, eval_mode="binary_positive", pos_tpl="STD Positive ({detected})")
log("Interpretation profiles ensured")

# 8) Dynamic form for STD risk collection
form_model = env["lab.dynamic.form"].sudo()
form_field_model = env["lab.dynamic.form.field"].sudo()
profile_form_rel = env["lab.profile.dynamic.form.rel"].sudo()

std_form = form_model.search([("code", "=", "STD_RISK_FORM"), ("company_id", "=", company.id)], limit=1)
if not std_form:
    std_form = form_model.create(
        {
            "name": "STD Risk & Consent Form",
            "code": "STD_RISK_FORM",
            "description": "Collect exposure history and consent for STD molecular panel.",
            "company_id": company.id,
            "active": True,
        }
    )
field_defs = [
    ("recent_contact", "Recent risky contact in past 3 months?", "selection", True, "no:No\nyes:Yes"),
    ("symptom_days", "Symptom duration (days)", "number", False, ""),
    ("consent_confirmed", "Informed consent confirmed", "boolean", True, ""),
    ("remarks", "Additional clinical remarks", "textarea", False, ""),
]
for idx, (key, name, ftype, required, options) in enumerate(field_defs, start=1):
    fld = form_field_model.search([("form_id", "=", std_form.id), ("key", "=", key)], limit=1)
    vals = {
        "form_id": std_form.id,
        "sequence": idx * 10,
        "name": name,
        "key": key,
        "field_type": ftype,
        "required": required,
        "active": True,
        "selection_options": options,
    }
    if fld:
        fld.write(vals)
    else:
        form_field_model.create(vals)

for p in [std3_profile, std4_profile, std6_profile, std7_profile]:
    rel = profile_form_rel.search([("profile_id", "=", p.id), ("form_id", "=", std_form.id)], limit=1)
    if not rel:
        profile_form_rel.create({"profile_id": p.id, "form_id": std_form.id, "sequence": 10})

log("Dynamic form configured and linked to STD panels")

# 9) Reagent kits + lots (multiplex)
kit_model = env["lab.assay.kit"].sudo()
lot_model = env["lab.reagent.lot"].sudo()

hpv_kit = kit_model.search([("code", "=", "HPV14-CHIP-KIT")], limit=1)
if not hpv_kit:
    hpv_kit = kit_model.create(
        {
            "name": "HPV14 Genotyping Chip Kit",
            "code": "HPV14-CHIP-KIT",
            "method": "multiplex_pcr",
            "vendor": "iMyTest",
            "manufacturer": "iMyTest",
            "covered_service_ids": [(6, 0, hpv_services.ids)],
            "default_reactions_per_kit": 96.0,
            "active": True,
        }
    )
else:
    hpv_kit.write({"covered_service_ids": [(6, 0, hpv_services.ids)]})

std_kit = kit_model.search([("code", "=", "STD7-MPX-KIT")], limit=1)
if not std_kit:
    std_kit = kit_model.create(
        {
            "name": "STD7 Multiplex PCR Kit",
            "code": "STD7-MPX-KIT",
            "method": "multiplex_pcr",
            "vendor": "iMyTest",
            "manufacturer": "iMyTest",
            "covered_service_ids": [(6, 0, std_services.ids)],
            "default_reactions_per_kit": 96.0,
            "active": True,
        }
    )
else:
    std_kit.write({"covered_service_ids": [(6, 0, std_services.ids)]})

for lot_no, kit in [("HPV14-LOT-DEMO", hpv_kit), ("STD7-LOT-DEMO", std_kit)]:
    lot = lot_model.search([("lot_number", "=", lot_no)], limit=1)
    vals = {
        "name": lot_no,
        "reagent_scope": "panel",
        "assay_kit_id": kit.id,
        "lot_number": lot_no,
        "vendor": "iMyTest",
        "received_date": fields.Date.today(),
        "opened_date": fields.Date.today(),
        "expiry_date": fields.Date.add(fields.Date.today(), years=1),
        "reactions_total": 960.0,
        "active": True,
    }
    if lot:
        lot.write(vals)
    else:
        lot_model.create(vals)

log("Assay kits and reagent lots ensured")

# 10) Report templates + institution binding + AI prompt
report_tpl_model = env["lab.report.template"].sudo()
classic_tpl = report_tpl_model.search([("code", "=", "classic"), ("company_id", "=", company.id)], limit=1)
clinical_tpl = report_tpl_model.search([("code", "=", "clinical"), ("company_id", "=", company.id)], limit=1)
compact_tpl = report_tpl_model.search([("code", "=", "compact"), ("company_id", "=", company.id)], limit=1)

if classic_tpl:
    classic_tpl.write(
        {
            "ai_interpretation_enabled": True,
            "show_ai_summary_in_pdf": True,
            "ai_auto_generate_on_release": False,
            "ai_temperature": 0.2,
            "ai_system_prompt": "You are a clinical lab interpretation assistant. Educational only.",
            "ai_user_prompt_template": (
                "Language: {output_language}\\n"
                "Accession: {accession}\\n"
                "Template: {report_template}\\n"
                "Snapshot:\\n{report_snapshot}\\n"
                "Results:\\n{analysis_lines}\\n"
                "Please output: key findings, interpretation, limitations, follow-up."
            ),
        }
    )

if clinical_tpl:
    institution.write({"lab_default_report_template_id": clinical_tpl.id})
elif classic_tpl:
    institution.write({"lab_default_report_template_id": classic_tpl.id})

log("Report templates and institution default template configured")

# 11) Request type scope: individual/institution allowed catalogs
type_model = env["lab.request.type"].sudo()
rt_ind = type_model.search([("code", "=", "individual"), ("company_id", "=", company.id)], limit=1)
rt_ins = type_model.search([("code", "=", "institution"), ("company_id", "=", company.id)], limit=1)

if rt_ind:
    rt_ind.write(
        {
            "allowed_service_ids": [(6, 0, (chem_services[0] | std_services | hpv_services | path_svc).ids)],
            "allowed_profile_ids": [(6, 0, (std3_profile | std4_profile | std6_profile | std7_profile | hpv14_profile | path_profile).ids)],
            "exclude_selected_services": False,
            "exclude_selected_profiles": False,
        }
    )
if rt_ins:
    rt_ins.write(
        {
            "allowed_service_ids": [(6, 0, (std_services | hpv_services | path_svc | chem_services[0]).ids)],
            "allowed_profile_ids": [(6, 0, (std3_profile | std4_profile | std6_profile | std7_profile | hpv14_profile | path_profile).ids)],
            "exclude_selected_services": False,
            "exclude_selected_profiles": False,
        }
    )

log("Request type catalog scopes configured")

# 12) Demo patient
patient_model = env["lab.patient"].sudo()
portal01_patient = patient_model.search([("identifier", "=", "DEMO-PAT-001"), ("company_id", "=", company.id)], limit=1)
if not portal01_patient:
    portal01_patient = patient_model.create(
        {
            "name": "Demo Patient 001",
            "identifier": "DEMO-PAT-001",
            "passport_no": "P-DEMO-001",
            "gender": "female",
            "phone": "13900000009",
            "email": "demo.patient001@imytest.local",
            "birthdate": fields.Date.from_string("1990-01-01"),
            "partner_id": portal01_partner.id,
            "company_id": company.id,
        }
    )

# 13) Create one full-flow request (individual STD7)
req_model = env["lab.test.request"].sudo()
full_req = req_model.create(
    {
        "requester_partner_id": portal01_partner.id,
        "request_type": "individual",
        "patient_id": portal01_patient.id,
        "patient_name": portal01_patient.name,
        "patient_identifier": portal01_patient.identifier,
        "patient_phone": portal01_patient.phone,
        "physician_partner_id": physician_model.search([("code", "=", "DR-DEMO-GYN-01"), ("company_id", "=", company.id)], limit=1).id,
        "physician_name": "Dr. Alice Gyn",
        "requested_collection_date": now,
        "priority": "routine",
        "clinical_note": "Demo STD7 full workflow.",
        "line_ids": [
            (
                0,
                0,
                {
                    "line_type": "profile",
                    "profile_id": std7_profile.id,
                    "specimen_ref": "SP1",
                    "specimen_barcode": "DEMO-STD7-SP1",
                    "specimen_sample_type": "swab",
                    "note": "STD7 demo",
                },
            )
        ],
        "company_id": company.id,
    }
)
full_req._apply_dynamic_form_payload(
    {
        "STD_RISK_FORM": {
            "recent_contact": "yes",
            "symptom_days": 7,
            "consent_confirmed": True,
            "remarks": "Demo auto-filled dynamic form payload.",
        }
    },
    source="manual",
)
full_req.action_submit()
full_req.action_start_triage()
full_req.action_prepare_quote()
full_req.action_approve_quote()
full_req.action_create_samples()

sample = full_req.sample_ids[:1]
if sample:
    sample.action_receive()
    sample.action_start()
    lot_std = lot_model.search([("lot_number", "=", "STD7-LOT-DEMO")], limit=1)
    for a in sample.analysis_ids:
        a.write({"reagent_lot_id": lot_std.id, "result_value": "32.0"})
        a.action_mark_done()
        if a.state != "verified":
            a.action_verify_result()
    sample.action_mark_to_verify()
    sample.action_verify()
    sample.action_approve_technical_review()
    sample.action_approve_medical_review()
    sample.action_release_report()

log("One full STD7 request workflow generated (request -> sample -> report)")

# 14) Plate demo: create many pending HPV analyses and load into 96-well batch
plate_req = req_model.create(
    {
        "requester_partner_id": portal_inst_partner.commercial_partner_id.id,
        "request_type": "institution",
        "client_partner_id": institution.id,
        "patient_name": "Plate Demo Placeholder",
        "patient_identifier": "PLATE-DEMO-HEAD",
        "patient_phone": "13800009999",
        "priority": "routine",
        "clinical_note": "Bulk HPV plate demo",
        "line_ids": [],
        "company_id": company.id,
    }
)

# 24 specimens x HPV14 panel = 336 analyses (enough for 96-well mapping use case)
line_cmds = []
for i in range(1, 25):
    line_cmds.append(
        (
            0,
            0,
            {
                "line_type": "profile",
                "profile_id": hpv14_profile.id,
                "specimen_ref": f"SP{i}",
                "specimen_barcode": f"HPV-DEMO-{i:03d}",
                "specimen_sample_type": "cervical_swab",
                "note": "HPV14 bulk demo",
            },
        )
    )
plate_req.write({"line_ids": line_cmds})
plate_req.action_submit()
plate_req.action_start_triage()
plate_req.action_prepare_quote()
plate_req.action_approve_quote()
plate_req.action_create_samples()

plate_model = env["lab.plate.batch"].sudo()
plate = plate_model.create(
    {
        "department": "microbiology",
        "service_id": hpv_services.sorted("code")[:1].id,
        "plate_format": "96",
        "company_id": company.id,
        "note": "Demo 96-well plate for HPV workflow learning",
    }
)
plate.action_auto_assign_pending()
plate.action_create_worksheet()

log(f"Plate demo prepared: {plate.name}, assigned_wells={plate.assigned_wells}, remaining_wells={plate.remaining_wells}")

# 15) Pathology demo (from one created sample)
path_req = req_model.create(
    {
        "requester_partner_id": portal01_partner.id,
        "request_type": "individual",
        "patient_id": portal01_patient.id,
        "patient_name": portal01_patient.name,
        "patient_identifier": portal01_patient.identifier,
        "priority": "routine",
        "clinical_note": "Pathology demo request",
        "line_ids": [
            (0, 0, {"line_type": "service", "service_id": path_svc.id, "specimen_ref": "SP1", "specimen_sample_type": "ffpe"})
        ],
        "company_id": company.id,
    }
)
path_req.action_submit()
path_req.action_start_triage()
path_req.action_prepare_quote()
path_req.action_approve_quote()
path_req.action_create_samples()
path_sample = path_req.sample_ids[:1]
if path_sample:
    action = path_sample.action_create_pathology_case()
    path_case = env["lab.pathology.case"].sudo().browse(action.get("res_id"))
    path_case.write(
        {
            "clinical_history": "<p>Persistent high-risk HPV with abnormal cytology history.</p>",
            "gross_description": "<p>Two tan-white tissue fragments, aggregate 0.4 cm.</p>",
            "microscopic_description": "<p>Squamous epithelium shows koilocytic changes and focal dysplasia.</p>",
            "final_diagnosis": "<p><strong>CIN II (HSIL)</strong></p>",
            "interpretation_comment": "<p>Recommend colposcopic correlation and guideline-based management.</p>",
        }
    )
    sp = env["lab.pathology.specimen"].sudo().create(
        {
            "case_id": path_case.id,
            "specimen_type": "ffpe",
            "specimen_site": "Cervix",
            "container_no": "PATH-CUP-001",
            "fixative": "10% neutral buffered formalin",
            "company_id": company.id,
        }
    )
    env["lab.pathology.slide"].sudo().create(
        {
            "specimen_id": sp.id,
            "block_id": "A1",
            "stain_method": "H&E",
            "stain_result": "Diagnostic",
            "company_id": company.id,
        }
    )
    path_case.action_set_accessioned()
    path_case.action_set_grossing()
    path_case.action_set_microscopy()
    path_case.action_set_diagnosed()
    path_case.action_set_reviewed()
    path_case.action_release_report()
    log(f"Pathology case demo generated: {path_case.name}")

# 16) Final summary
print("=" * 80)
print("FULL DEMO CONFIGURATION COMPLETED")
print("Company:", company.name)
for line in summary:
    print("-", line)
print("Portal Individual:", "portal-01@imytest.local / Portal@12345")
print("Portal Institution:", "portal-inst-01@imytest.local / Portal@12345")
print("Learning Entry Menus:")
print("  1) Operations > Test Requests / Samples / Analysis Queue / Worksheets")
print("  2) Operations > Plate Batches (96-well demo)")
print("  3) Operations > Pathology > Pathology Cases")
print("  4) Configuration > Test Catalog / Report Templates / Interpretation Profiles / Dynamic Forms")
print("=" * 80)
env.cr.commit()
