from time import perf_counter
from odoo import fields

BATCH_TAG = 'LOADTEST5000_20260222'
TOTAL = 5000
COMMIT_EVERY = 10

start = perf_counter()

company = env.company
request_model = env['lab.test.request'].sudo()
sample_model = env['lab.sample'].sudo()
service_model = env['lab.service'].sudo()
partner_model = env['res.partner'].sudo()
report_template = env['lab.report.template'].sudo().search([('code', '=', 'classic')], limit=1)

# Lightweight service for performance test
service = service_model.search([('code', '=', 'LOADTEST-PCR')], limit=1)
if not service:
    service = service_model.create({
        'name': 'Load Test PCR Ct',
        'code': 'LOADTEST-PCR',
        'department': 'microbiology',
        'sample_type': 'swab',
        'result_type': 'numeric',
        'unit': 'Ct',
        'ref_min': 0.0,
        'ref_max': 45.0,
        'auto_binary_enabled': True,
        'auto_binary_cutoff': 33.0,
        'auto_binary_negative_when_gte': True,
        'require_qc': False,
        'require_reagent_lot': False,
        'turnaround_hours': 12,
        'list_price': 99.0,
        'active': True,
        'note': BATCH_TAG,
    })

# Shared requester/patient to reduce overhead
requester = partner_model.search([('email', '=', 'loadtest.requester@imytest.local')], limit=1)
if not requester:
    requester = partner_model.create({'name': 'Loadtest Requester', 'email': 'loadtest.requester@imytest.local', 'company_id': company.id})

patient = partner_model.search([('email', '=', 'loadtest.patient@imytest.local')], limit=1)
if not patient:
    patient = partner_model.create({'name': 'Loadtest Patient', 'email': 'loadtest.patient@imytest.local', 'company_id': company.id})

# Optional physician
physician = partner_model.search([
    ('is_lab_physician', '=', True),
    '|', ('lab_physician_company_id', '=', False), ('lab_physician_company_id', '=', company.id),
], limit=1)

created_request_ids = []
created_sample_ids = []
errors = 0

for i in range(1, TOTAL + 1):
    seq = f"{i:05d}"
    req_name_hint = f"{BATCH_TAG}-{seq}"
    try:
        req_vals = {
            'requester_partner_id': requester.id,
            'request_type': 'individual',
            'patient_id': patient.id,
            'patient_name': patient.name,
            'patient_identifier': req_name_hint,
            'patient_gender': 'female' if i % 2 else 'male',
            'patient_phone': '13000000000',
            'priority': 'routine',
            'sample_type': 'swab',
            'clinical_note': BATCH_TAG,
            'requested_collection_date': fields.Datetime.now(),
            'preferred_template_id': report_template.id if report_template else False,
            'company_id': company.id,
            'line_ids': [
                (0, 0, {
                    'line_type': 'service',
                    'service_id': service.id,
                    'quantity': 1,
                    'note': BATCH_TAG,
                    'specimen_ref': 'SP1',
                    'specimen_barcode': f'{BATCH_TAG}-BC-{seq}',
                    'specimen_sample_type': 'swab',
                })
            ],
        }
        if physician:
            req_vals.update({'physician_partner_id': physician.id, 'physician_name': physician.name})

        req = request_model.create(req_vals)
        req.action_submit()
        req.action_start_triage()
        req.action_prepare_quote()
        req.action_approve_quote()
        req.action_create_samples()

        sample = req.sample_ids[:1]
        if not sample:
            raise Exception('No sample generated')

        sample.action_receive()
        sample.action_start()

        for line in sample.analysis_ids:
            # deterministic variation
            result_value = '31.0' if (i % 4 == 0) else '38.0'
            line.write({'result_value': result_value, 'analyst_id': env.user.id})
            line.action_mark_done()

        sample.action_mark_to_verify()
        sample.action_verify()

        sample.write({
            'technical_review_note': f'{BATCH_TAG} technical review',
            'medical_review_note': f'{BATCH_TAG} medical review',
        })
        sample.action_approve_technical_review()
        sample.action_approve_medical_review()
        sample.action_release_report()
        req.action_mark_completed()

        # Pressure-test AI mode: persist simulated AI output without external API
        fake_text = (
            f"[{BATCH_TAG}] Simulated AI interpretation for {sample.name}.\\n"
            f"Result summary: {'Positive' if i % 4 == 0 else 'Negative'}.\\n"
            "This content is generated in load test mode."
        )
        sample.write({
            'ai_interpretation_state': 'done',
            'ai_interpretation_text': fake_text,
            'ai_interpretation_error': False,
            'ai_interpretation_model': 'loadtest-simulated',
            'ai_interpretation_lang': 'English',
            'ai_interpretation_prompt': f'{BATCH_TAG} simulated prompt',
            'ai_interpretation_updated_at': fields.Datetime.now(),
            'ai_review_state': 'approved',
            'ai_reviewed_by_id': env.user.id,
            'ai_reviewed_at': fields.Datetime.now(),
            'ai_review_note': 'Auto-approved in load test mode',
        })
        env['lab.sample.ai.interpretation'].sudo().create({
            'sample_id': sample.id,
            'state': 'done',
            'trigger_source': 'manual',
            'model_name': 'loadtest-simulated',
            'output_language': 'English',
            'duration_ms': 5,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
            'system_prompt': 'loadtest',
            'user_prompt': BATCH_TAG,
            'response_text': fake_text,
            'generated_at': fields.Datetime.now(),
        })
        env['lab.sample.ai.review.log'].sudo().create({
            'sample_id': sample.id,
            'action': 'approved',
            'reviewer_id': env.user.id,
            'note': 'loadtest auto approve',
            'reviewed_at': fields.Datetime.now(),
        })

        created_request_ids.append(req.id)
        created_sample_ids.append(sample.id)

    except Exception as exc:
        errors += 1
        env.cr.rollback()
        print(f'ERROR {i}: {exc}', flush=True)
        continue

    if i % COMMIT_EVERY == 0:
        env.cr.commit()
        elapsed = perf_counter() - start
        print(
            f'PROGRESS {i}/{TOTAL} elapsed={elapsed:.1f}s '
            f'created_requests={len(created_request_ids)} created_samples={len(created_sample_ids)} errors={errors}',
            flush=True,
        )

# final commit
env.cr.commit()
elapsed = perf_counter() - start
print('DONE', flush=True)
print('BATCH_TAG', BATCH_TAG, flush=True)
print('TOTAL_TARGET', TOTAL, flush=True)
print('CREATED_REQUESTS', len(created_request_ids), flush=True)
print('CREATED_SAMPLES', len(created_sample_ids), flush=True)
print('ERRORS', errors, flush=True)
print('ELAPSED_SECONDS', round(elapsed, 2), flush=True)
print('AVG_MS_PER_RECORD', round((elapsed * 1000.0) / max(len(created_request_ids), 1), 2), flush=True)
