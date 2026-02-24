# Odoo shell script (expects `env` in globals)
from odoo import fields

summary = []
company = env.company
admin_user = env.user
param_model = env['ir.config_parameter'].sudo()
enable_ai = (param_model.get_param('laboratory_management.test_enable_ai') or '').strip() == '1'
# Avoid SMTP provider throttling from blocking smoke tests.
param_model.set_param('laboratory_management.dispatch_email_enabled', '0')

# 1) Master data i18n seed
env['lab.master.data.mixin'].seed_i18n_master_data()
summary.append('Master data i18n seeded')

# 2) Ensure extra sample types for STD/PCR scenarios
sample_type_model = env['lab.sample.type'].sudo()
extra_sample_types = [
    ('cervical_swab', {'en_US': 'Cervical Swab'}),
    ('urethral_swab', {'en_US': 'Urethral Swab'}),
    ('vaginal_swab', {'en_US': 'Vaginal Swab'}),
    ('first_void_urine', {'en_US': 'First-void Urine'}),
]
for code, names in extra_sample_types:
    rec = sample_type_model.search([('code', '=', code)], limit=1)
    if not rec:
        rec = sample_type_model.create({'code': code, 'name': names['en_US'], 'sequence': 90, 'active': True})
    for lang, value in names.items():
        rec.with_context(lang=lang).write({'name': value})
summary.append('Extra sample types ensured')

# 3) Physician department
phy_dept_model = env['lab.physician.department'].sudo()
phy_dept = phy_dept_model.search([('code', '=', 'GYN'), ('company_id', '=', company.id)], limit=1)
if not phy_dept:
    phy_dept = phy_dept_model.create({'name': 'Gynecology', 'code': 'GYN', 'company_id': company.id})
summary.append(f'Physician department: {phy_dept.name}')

# 4) Institution + physician partner
partner_model = env['res.partner'].sudo()
patient_model = env['lab.patient'].sudo()
physician_model = env['lab.physician'].sudo()
institution = partner_model.search([('name', '=', 'iMyTest Women Health Center')], limit=1)
if not institution:
    institution = partner_model.create({'name': 'iMyTest Women Health Center', 'is_company': True, 'company_type': 'company'})

physician = physician_model.search([('code', '=', 'DR-LIN-MEI'), ('company_id', '=', company.id)], limit=1)
if not physician:
    physician = physician_model.create({
        'name': 'Dr. Lin Mei',
        'code': 'DR-LIN-MEI',
        'company_id': company.id,
        'lab_physician_department_id': phy_dept.id,
        'institution_partner_id': institution.id,
        'email': 'dr.lin.mei@imytest.local',
    })
summary.append(f'Physician: {physician.name}')

# 5) Portal users
portal_group = env.ref('base.group_portal')

def ensure_portal_user(login, name, password, partner):
    user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
    vals = {
        'name': name,
        'login': login,
        'partner_id': partner.id,
        'active': True,
        'password': password,
        'group_ids': [(6, 0, [portal_group.id])],
    }
    if user:
        user.write(vals)
    else:
        user = env['res.users'].sudo().with_context(no_reset_password=True).create(vals)
    return user

# individual portal-01
portal01_partner = partner_model.search([('email', '=', 'portal-01@imytest.local')], limit=1)
if not portal01_partner:
    portal01_partner = partner_model.create({'name': 'Portal 01', 'email': 'portal-01@imytest.local', 'phone': '13900000001'})
portal01_user = ensure_portal_user('portal-01@imytest.local', 'portal-01', 'Portal@12345', portal01_partner)
portal01_patient = patient_model.search([('partner_id', '=', portal01_partner.id)], limit=1)
if not portal01_patient:
    portal01_patient = patient_model.create({
        'name': portal01_partner.name,
        'identifier': 'PORTAL01-PAT',
        'gender': 'unknown',
        'phone': portal01_partner.phone,
        'email': portal01_partner.email,
        'partner_id': portal01_partner.id,
        'company_id': company.id,
    })

# institutional portal user
inst_portal_partner = partner_model.search([('email', '=', 'portal-inst-01@imytest.local')], limit=1)
if not inst_portal_partner:
    inst_portal_partner = partner_model.create({
        'name': 'Institution Portal 01',
        'email': 'portal-inst-01@imytest.local',
        'parent_id': institution.id,
    })
inst_portal_user = ensure_portal_user('portal-inst-01@imytest.local', 'portal-inst-01', 'Portal@12345', inst_portal_partner)
summary.append('Portal users ensured')

# 6) STD 7 services
service_model = env['lab.service'].sudo()
services_spec = [
    ('std_ct', 'Chlamydia trachomatis PCR Ct', 'CT-PCR-CT', '33.0'),
    ('std_uu', 'Ureaplasma urealyticum PCR Ct', 'UU-PCR-CT', '33.0'),
    ('std_ng', 'Neisseria gonorrhoeae PCR Ct', 'NG-PCR-CT', '33.0'),
    ('std_hsv1', 'HSV-I PCR Ct', 'HSV1-PCR-CT', '33.0'),
    ('std_hsv2', 'HSV-II PCR Ct', 'HSV2-PCR-CT', '33.0'),
    ('std_can', 'Candida albicans PCR Ct', 'CAN-PCR-CT', '33.0'),
    ('std_gv', 'Gardnerella vaginalis PCR Ct', 'GV-PCR-CT', '33.0'),
]
std_services = env['lab.service']
for _, name, code, cutoff in services_spec:
    svc = service_model.search([('code', '=', code)], limit=1)
    vals = {
        'name': name,
        'code': code,
        'department': 'microbiology',
        'sample_type': 'swab' if 'HSV' not in code and 'GV' not in code else 'swab',
        'result_type': 'numeric',
        'unit': 'Ct',
        'ref_min': 0.0,
        'ref_max': 45.0,
        'critical_min': 0.0,
        'critical_max': 45.0,
        'auto_binary_enabled': True,
        'auto_binary_cutoff': float(cutoff),
        'auto_binary_negative_when_gte': True,
        'require_reagent_lot': True,
        'turnaround_hours': 24,
        'list_price': 199.0,
        'active': True,
    }
    if svc:
        svc.write(vals)
    else:
        svc = service_model.create(vals)
    std_services |= svc
summary.append(f'STD services ensured: {len(std_services)}')

# 7) Interpretation profile for STD7
interp_model = env['lab.interpretation.profile'].sudo()
interp_line_model = env['lab.interpretation.profile.line'].sudo()
interp = interp_model.search([('code', '=', 'STD7-PCR')], limit=1)
if not interp:
    interp = interp_model.create({
        'name': 'STD 7-Pathogen PCR Interpretation',
        'code': 'STD7-PCR',
        'service_match_mode': 'all_required',
        'minimum_required_count': 1,
        'positive_summary_template': 'Positive ({detected} detected)',
        'negative_summary_text': 'Negative',
        'inconclusive_summary_text': 'Inconclusive',
    })
existing_line_service_ids = set(interp.line_ids.mapped('service_id').ids)
for svc in std_services:
    if svc.id in existing_line_service_ids:
        continue
    interp_line_model.create({
        'profile_id': interp.id,
        'service_id': svc.id,
        'label': svc.name.replace(' PCR Ct', ''),
        'evaluation_mode': 'binary_positive',
        'include_in_detected': True,
        'active': True,
    })
summary.append('Interpretation profile ensured')

# 8) Profile packages 3/4/6/7 to validate multiplex kit + different bundles
profile_model = env['lab.profile'].sudo()
profile_line_model = env['lab.profile.line'].sudo()
svc_by_code = {s.code: s for s in std_services}
package_defs = {
    'STD3-PCR': ['CT-PCR-CT', 'UU-PCR-CT', 'NG-PCR-CT'],
    'STD4-PCR': ['CT-PCR-CT', 'UU-PCR-CT', 'NG-PCR-CT', 'HSV2-PCR-CT'],
    'STD6-PCR': ['CT-PCR-CT', 'UU-PCR-CT', 'NG-PCR-CT', 'HSV1-PCR-CT', 'HSV2-PCR-CT', 'CAN-PCR-CT'],
    'STD7-PCR': ['CT-PCR-CT', 'UU-PCR-CT', 'NG-PCR-CT', 'HSV1-PCR-CT', 'HSV2-PCR-CT', 'CAN-PCR-CT', 'GV-PCR-CT'],
}
profiles = {}
for code, code_list in package_defs.items():
    profile = profile_model.search([('code', '=', code)], limit=1)
    if not profile:
        profile = profile_model.create({'name': f'{code} Panel', 'code': code, 'active': True})
    profile.line_ids.unlink()
    for svc_code in code_list:
        svc = svc_by_code[svc_code]
        profile_line_model.create({'profile_id': profile.id, 'service_id': svc.id})
    profiles[code] = profile
summary.append('Profiles ensured: STD3/4/6/7')

# 9) Multiplex assay kit + panel lot covering all 7 services
kit_model = env['lab.assay.kit'].sudo()
lot_model = env['lab.reagent.lot'].sudo()
kit = kit_model.search([('code', '=', 'STD7-MPX-KIT')], limit=1)
if not kit:
    kit = kit_model.create({
        'name': 'STD 7 Multiplex PCR Kit',
        'code': 'STD7-MPX-KIT',
        'vendor': 'iMyTest',
        'manufacturer': 'iMyTest',
        'method': 'multiplex_pcr',
        'covered_service_ids': [(6, 0, std_services.ids)],
        'default_reactions_per_kit': 96.0,
        'active': True,
    })
else:
    kit.write({'covered_service_ids': [(6, 0, std_services.ids)]})

lot = lot_model.search([('lot_number', '=', 'STD7-LOT-20260221')], limit=1)
if not lot:
    lot = lot_model.create({
        'name': 'STD7 Multiplex Reagent Lot',
        'reagent_scope': 'panel',
        'assay_kit_id': kit.id,
        'lot_number': 'STD7-LOT-20260221',
        'vendor': 'iMyTest',
        'received_date': fields.Date.today(),
        'opened_date': fields.Date.today(),
        'expiry_date': fields.Date.add(fields.Date.today(), years=1),
        'reactions_total': 96.0,
        'active': True,
    })
summary.append(f'Reagent lot: {lot.lot_number}')

# 10) AI + report template prompt setup (classic template)
report_tpl = env['lab.report.template'].sudo().search([('code', '=', 'classic')], limit=1)
if report_tpl:
    report_tpl.write({
        'ai_interpretation_enabled': bool(enable_ai),
        'ai_auto_generate_on_release': False,
        'show_ai_summary_in_pdf': True,
        'ai_system_prompt': (
            'You are a laboratory report interpretation assistant for molecular infectious disease PCR testing. '
            'Provide educational interpretation only; do not provide diagnosis or treatment decisions.'
        ),
        'ai_user_prompt_template': (
            'Language: {output_language}\\n'
            'Accession: {accession}\\n'
            'Patient: {patient_name}\\n'
            'Clinical note: {sample_note}\\n\\n'
            'Report Snapshot:\\n{report_snapshot}\\n\\n'
            'Results:\\n{analysis_lines}\\n\\n'
            'Abnormal:\\n{abnormal_lines}\\n\\n'
            'Please output with sections:\\n'
            '1) Key findings\\n'
            '2) Pathogen-by-pathogen interpretation\\n'
            '3) Risk and limitation notes\\n'
            '4) Follow-up suggestions\\n'
            'Keep concise and factual.'
        ),
        'ai_temperature': 0.2,
    })
summary.append('Classic report AI prompt updated')

# 11) Build test request -> sample -> analysis -> review -> report release
request_model = env['lab.test.request'].sudo()
req = request_model.create({
    'requester_partner_id': portal01_partner.id,
    'request_type': 'individual',
    'patient_id': portal01_patient.id,
    'patient_name': 'Test Patient STD',
    'patient_identifier': 'ID-STD-001',
    'patient_gender': 'female',
    'patient_phone': '13900000009',
    'physician_partner_id': physician.id,
    'physician_name': physician.name,
    'requested_collection_date': fields.Datetime.now(),
    'priority': 'routine',
    'sample_type': 'swab',
    'clinical_note': 'STD 7 multiplex PCR panel test data flow.',
    'line_ids': [
        (0, 0, {
            'line_type': 'profile',
            'profile_id': profiles['STD7-PCR'].id,
            'specimen_ref': 'SP1',
            'specimen_sample_type': 'swab',
            'specimen_barcode': 'SP1-STD7-001',
            'quantity': 1,
        })
    ],
})
req.action_submit()
req.action_start_triage()
req.action_prepare_quote()
req.action_approve_quote()
req.action_create_samples()
sample = req.sample_ids[:1]
if not sample:
    raise Exception('No sample created from request')

sample.action_receive()
sample.action_start()

# Fill results and assign same panel lot to all analyses
ct_values = {
    'CT-PCR-CT': '31.2',
    'UU-PCR-CT': '37.8',
    'NG-PCR-CT': '39.5',
    'HSV1-PCR-CT': '40.0',
    'HSV2-PCR-CT': '35.2',
    'CAN-PCR-CT': '38.1',
    'GV-PCR-CT': '30.7',
}
for line in sample.analysis_ids:
    val = ct_values.get(line.service_id.code, '40.0')
    line.write({'result_value': val, 'analyst_id': admin_user.id, 'reagent_lot_id': lot.id})
    line.action_mark_done()

sample.action_mark_to_verify()
sample.action_verify()

# dual review and release
sample.write({'technical_review_note': 'Technical check passed', 'medical_review_note': 'Medical check passed'})
sample.action_approve_technical_review()
sample.action_approve_medical_review()
sample.action_release_report()
req.action_mark_completed()

# AI generation (only if key/base available)
ai_status = 'skipped'
try:
    if not enable_ai:
        raise Exception('disabled_by_test_flag')
    provider = (param_model.get_param('laboratory_management.ai_provider') or 'openai').strip()
    if provider == 'openai':
        key = (param_model.get_param('laboratory_management.openai_api_key') or '').strip()
        ready = bool(key)
    elif provider == 'openai_compatible':
        base = (param_model.get_param('laboratory_management.openai_compatible_base_url') or '').strip()
        ready = bool(base)
    else:
        base = (param_model.get_param('laboratory_management.ollama_base_url') or '').strip()
        ready = bool(base)

    if ready:
        sample.with_context(force_ai_regenerate=True, ai_trigger_source='manual').action_generate_ai_interpretation()
        if sample.ai_interpretation_state == 'done':
            sample.write({'ai_review_note': 'Reviewed in automated demo flow'})
            sample.action_approve_ai_interpretation()
            ai_status = 'done+approved'
        else:
            ai_status = f"state={sample.ai_interpretation_state}"
    else:
        ai_status = 'skipped(not configured)'
except Exception as exc:
    ai_status = f'skipped({exc})'

# Ensure dispatch sent
dispatches = env['lab.report.dispatch'].sudo().search([('sample_id', '=', sample.id)])
if dispatches:
    dispatches.filtered(lambda d: d.state == 'draft').action_mark_sent()

# Add explicit requester dispatch to ensure individual portal user can view report list directly.
req_dispatch = env['lab.report.dispatch'].sudo().search(
    [('sample_id', '=', sample.id), ('partner_id', '=', portal01_partner.id)], limit=1
)
if not req_dispatch:
    req_dispatch = env['lab.report.dispatch'].sudo().create(
        {'sample_id': sample.id, 'partner_id': portal01_partner.id, 'channel': 'portal'}
    )
if req_dispatch.state == 'draft':
    req_dispatch.action_mark_sent()

# 12) Institution flow with 5 patients (batch-like test set)
inst_requests = env['lab.test.request']
inst_samples = env['lab.sample']
inst_profile_codes = ['STD3-PCR', 'STD4-PCR', 'STD6-PCR', 'STD7-PCR', 'STD7-PCR']
for idx in range(1, 6):
    p_name = f'Inst Patient {idx:02d}'
    p_email = f'inst-patient-{idx:02d}@imytest.local'
    patient_partner = partner_model.search([('email', '=', p_email)], limit=1)
    if not patient_partner:
        patient_partner = partner_model.create({
            'name': p_name,
            'email': p_email,
            'phone': f'13800000{idx:03d}',
            'parent_id': institution.id,
        })
    patient = patient_model.search([('partner_id', '=', patient_partner.id)], limit=1)
    if not patient:
        patient = patient_model.create({
            'name': patient_partner.name,
            'identifier': f'INST-PAT-{idx:03d}',
            'gender': 'female' if idx % 2 else 'male',
            'phone': patient_partner.phone,
            'email': patient_partner.email,
            'partner_id': patient_partner.id,
            'company_id': company.id,
        })

    profile = profiles[inst_profile_codes[idx - 1]]
    inst_req = request_model.create({
        'requester_partner_id': inst_portal_partner.id,
        'request_type': 'institution',
        'client_partner_id': institution.id,
        'patient_id': patient.id,
        'patient_name': patient.name,
        'patient_identifier': f'INST-ID-{idx:03d}',
        'patient_gender': 'female' if idx % 2 else 'male',
        'physician_partner_id': physician.id,
        'physician_name': physician.name,
        'requested_collection_date': fields.Datetime.now(),
        'priority': 'routine',
        'sample_type': 'swab',
        'clinical_note': f'Institution batch test #{idx}',
        'line_ids': [
            (0, 0, {
                'line_type': 'profile',
                'profile_id': profile.id,
                'specimen_ref': 'SP1',
                'specimen_sample_type': 'swab',
                'specimen_barcode': f'INST-SP1-{idx:03d}',
                'quantity': 1,
            })
        ],
    })
    inst_req.action_submit()
    inst_req.action_start_triage()
    inst_req.action_prepare_quote()
    inst_req.action_approve_quote()
    inst_req.action_create_samples()
    inst_sample = inst_req.sample_ids[:1]
    if not inst_sample:
        continue
    inst_sample.action_receive()
    inst_sample.action_start()
    for line in inst_sample.analysis_ids:
        line.write({'result_value': '39.0', 'analyst_id': admin_user.id, 'reagent_lot_id': lot.id})
        line.action_mark_done()
    inst_sample.action_mark_to_verify()
    inst_sample.action_verify()
    inst_sample.write({'technical_review_note': 'Technical check passed', 'medical_review_note': 'Medical check passed'})
    inst_sample.action_approve_technical_review()
    inst_sample.action_approve_medical_review()
    inst_sample.action_release_report()
    inst_req.action_mark_completed()
    inst_requests |= inst_req
    inst_samples |= inst_sample

# Portal counters
portal_sample_count = env['lab.sample'].sudo().search_count([('patient_id', '=', portal01_patient.id)])
portal_request_count = env['lab.test.request'].sudo().search_count([('requester_partner_id', '=', portal01_partner.id)])
inst_portal_sample_count = env['lab.sample'].sudo().search_count([('client_id', 'child_of', institution.commercial_partner_id.id)])
inst_portal_request_count = env['lab.test.request'].sudo().search_count([('requester_partner_id', 'child_of', institution.commercial_partner_id.id)])

print('=== FULL SETUP + TEST DONE ===')
for item in summary:
    print('-', item)
print('Request:', req.name, '| state=', req.state)
print('Sample:', sample.name, '| state=', sample.state)
print('Dispatches:', len(dispatches), '| states=', ','.join(dispatches.mapped('state')))
print('Institution requests generated:', len(inst_requests))
print('Institution samples generated:', len(inst_samples))
print('AI:', ai_status)
print('Portal individual login:', 'portal-01@imytest.local', ' / ', 'Portal@12345')
print('Portal institution login:', 'portal-inst-01@imytest.local', ' / ', 'Portal@12345')
print('Portal partner sample count:', portal_sample_count)
print('Portal partner request count:', portal_request_count)
print('Institution portal sample count:', inst_portal_sample_count)
print('Institution portal request count:', inst_portal_request_count)
env.cr.commit()
