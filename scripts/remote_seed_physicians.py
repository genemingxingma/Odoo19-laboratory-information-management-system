# Odoo shell script: seed physician departments and physicians for portal demos
from odoo import fields

company = env.company
partner_model = env['res.partner'].sudo()
dept_model = env['lab.physician.department'].sudo()

# Ensure anchor partners
inst = partner_model.search([('name', '=', 'iMyTest Women Health Center')], limit=1)
if not inst:
    inst = partner_model.create({'name': 'iMyTest Women Health Center', 'is_company': True, 'company_type': 'company'})

portal01 = partner_model.search([('email', '=', 'portal-01@imytest.local')], limit=1)
if not portal01:
    portal01 = partner_model.create({'name': 'Portal 01', 'email': 'portal-01@imytest.local'})

# Departments
dept_defs = [
    ('GYN', 'Gynecology'),
    ('URO', 'Urology'),
    ('DERM', 'Dermatology'),
    ('INF', 'Infectious Disease'),
    ('GEN', 'General Practice'),
]

depts = {}
for code, name in dept_defs:
    d = dept_model.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
    if not d:
        d = dept_model.create({'code': code, 'name': name, 'company_id': company.id, 'active': True})
    depts[code] = d

# Doctors under institution (for institutional portal)
inst_docs = [
    ('dr.lin.mei@imytest.local', 'Dr. Lin Mei', 'GYN'),
    ('dr.somchai@imytest.local', 'Dr. Somchai K.', 'INF'),
    ('dr.anong@imytest.local', 'Dr. Anong P.', 'GEN'),
    ('dr.chen.yu@imytest.local', 'Dr. Chen Yu', 'DERM'),
    ('dr.arun@imytest.local', 'Dr. Arun S.', 'URO'),
]
for email, name, code in inst_docs:
    doc = partner_model.search([('email', '=', email)], limit=1)
    vals = {
        'name': name,
        'email': email,
        'is_company': False,
        'parent_id': inst.id,
        'type': 'contact',
        'is_lab_physician': True,
        'lab_physician_company_id': company.id,
        'lab_physician_department_id': depts[code].id,
        'active': True,
    }
    if doc:
        doc.write(vals)
    else:
        partner_model.create(vals)

# Doctors under portal-01 commercial tree (for individual portal to see options)
ind_docs = [
    ('dr.portal.ref1@imytest.local', 'Dr. Referral One', 'GEN'),
    ('dr.portal.ref2@imytest.local', 'Dr. Referral Two', 'INF'),
]
for email, name, code in ind_docs:
    doc = partner_model.search([('email', '=', email)], limit=1)
    vals = {
        'name': name,
        'email': email,
        'is_company': False,
        'parent_id': portal01.commercial_partner_id.id,
        'type': 'contact',
        'is_lab_physician': True,
        'lab_physician_company_id': company.id,
        'lab_physician_department_id': depts[code].id,
        'active': True,
    }
    if doc:
        doc.write(vals)
    else:
        partner_model.create(vals)

# Counts by portal domain logic
inst_phys_count = partner_model.search_count([
    ('is_company', '=', False),
    ('is_lab_physician', '=', True),
    ('lab_physician_company_id', 'in', env.companies.ids),
    ('parent_id', 'child_of', inst.commercial_partner_id.id),
    ('type', 'in', ('contact', 'other')),
])
ind_phys_count = partner_model.search_count([
    ('is_company', '=', False),
    ('is_lab_physician', '=', True),
    ('lab_physician_company_id', 'in', env.companies.ids),
    ('parent_id', 'child_of', portal01.commercial_partner_id.id),
    ('type', 'in', ('contact', 'other')),
])

print('Seed done')
print('Institution partner:', inst.name, '| physicians visible:', inst_phys_count)
print('Individual partner:', portal01.name, '| physicians visible:', ind_phys_count)
print('Departments:', ', '.join([d.name for d in dept_model.search([('company_id', '=', company.id), ('active', '=', True)], order='name asc')]))
