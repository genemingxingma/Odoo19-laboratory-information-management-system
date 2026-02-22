company = env.company
partner_model = env['res.partner'].sudo()
dept_model = env['lab.physician.department'].sudo()

# departments
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

# parent institution for grouping
inst = partner_model.search([('name', '=', 'iMyTest Women Health Center')], limit=1)
if not inst:
    inst = partner_model.create({'name': 'iMyTest Women Health Center', 'is_company': True, 'company_type': 'company'})

doctors = [
    ('dr.lin.mei@imytest.local', 'Dr. Lin Mei', 'GYN'),
    ('dr.somchai@imytest.local', 'Dr. Somchai K.', 'INF'),
    ('dr.anong@imytest.local', 'Dr. Anong P.', 'GEN'),
    ('dr.chen.yu@imytest.local', 'Dr. Chen Yu', 'DERM'),
    ('dr.arun@imytest.local', 'Dr. Arun S.', 'URO'),
    ('dr.nida@imytest.local', 'Dr. Nida T.', 'GYN'),
    ('dr.wang.li@imytest.local', 'Dr. Wang Li', 'INF'),
]

for email, name, dept_code in doctors:
    rec = partner_model.search([('email', '=', email)], limit=1)
    vals = {
        'name': name,
        'email': email,
        'is_company': False,
        'parent_id': inst.id,
        'type': 'contact',
        'active': True,
        'is_lab_physician': True,
        'lab_physician_department_id': depts[dept_code].id,
        'lab_physician_company_id': company.id,
    }
    if rec:
        rec.write(vals)
    else:
        partner_model.create(vals)

count_all = partner_model.search_count([('is_lab_physician', '=', True)])
count_visible = partner_model.search_count([
    ('is_lab_physician','=',True),
    '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','=',company.id)
])
print('done physicians all=', count_all, 'visible=', count_visible)
print('departments=', ', '.join(dept_model.search([('company_id','=',company.id)], order='name asc').mapped('name')))
