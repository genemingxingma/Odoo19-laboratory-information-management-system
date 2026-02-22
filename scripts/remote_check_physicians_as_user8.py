uid = 8
user = env['res.users'].sudo().browse(uid)
model = env['res.partner'].with_user(user)
domain = [
    ('is_lab_physician','=',True),
    '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','in', user.company_ids.ids)
]
count = model.search_count(domain)
print('user', user.login, 'company_ids=', user.company_ids.ids, 'count=', count)
recs = model.search(domain, limit=20)
for r in recs:
    print(r.id, r.name, 'dept=', r.lab_physician_department_id.name if r.lab_physician_department_id else '-', 'lab_co=', r.lab_physician_company_id.id if r.lab_physician_company_id else None)
