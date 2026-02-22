company = env.company
partner_model = env['res.partner'].sudo()
dept_model = env['lab.physician.department'].sudo()

# ensure departments
def ensure_dept(code, name):
    rec = dept_model.search([('code','=',code),('company_id','=',company.id)], limit=1)
    if not rec:
        rec = dept_model.create({'code': code, 'name': name, 'company_id': company.id, 'active': True})
    return rec

depts = {
    'GYN': ensure_dept('GYN', 'Gynecology'),
    'INF': ensure_dept('INF', 'Infectious Disease'),
    'GEN': ensure_dept('GEN', 'General Practice'),
    'DERM': ensure_dept('DERM', 'Dermatology'),
    'URO': ensure_dept('URO', 'Urology'),
}

inst = partner_model.search([('name','=','iMyTest Women Health Center')], limit=1)
if not inst:
    inst = partner_model.create({'name':'iMyTest Women Health Center', 'is_company':True, 'company_type':'company', 'company_id': company.id})

rows = [
    ('dr.lin.mei@imytest.local', 'Dr. Lin Mei', 'GYN'),
    ('dr.somchai@imytest.local', 'Dr. Somchai K.', 'INF'),
    ('dr.anong@imytest.local', 'Dr. Anong P.', 'GEN'),
    ('dr.chen.yu@imytest.local', 'Dr. Chen Yu', 'DERM'),
    ('dr.arun@imytest.local', 'Dr. Arun S.', 'URO'),
]
for email, name, dc in rows:
    rec = partner_model.search([('email','=',email)], limit=1)
    vals = {
        'name': name,
        'email': email,
        'parent_id': inst.id,
        'type': 'contact',
        'active': True,
        'is_company': False,
        'company_id': company.id,
        'is_lab_physician': True,
        'lab_physician_company_id': company.id,
        'lab_physician_department_id': depts[dc].id,
    }
    if rec:
        rec.write(vals)
    else:
        partner_model.create(vals)

sudo_count = partner_model.search_count([('is_lab_physician','=',True)])
print('sudo_count', sudo_count)

u = env['res.users'].sudo().search([('login','=','mingxingma@gmail.com')], limit=1)
if u:
    dom = [('is_lab_physician','=',True), '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','in',u.company_ids.ids)]
    visible = partner_model.with_user(u).search_count(dom)
    print('visible_for_mingxingma', visible)
    recs = partner_model.with_user(u).search(dom, limit=10)
    for r in recs:
        print(r.id, r.name)
