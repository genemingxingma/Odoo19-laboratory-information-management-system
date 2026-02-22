company_ids = env.companies.ids
print('current companies:', company_ids)
all_docs = env['res.partner'].sudo().search([('is_lab_physician','=',True)], order='id desc')
print('all is_lab_physician count=', len(all_docs))
for p in all_docs[:20]:
    print(p.id, p.name, 'active=', p.active, 'dept=', p.lab_physician_department_id.name if p.lab_physician_department_id else '-', 'lab_company=', p.lab_physician_company_id.id if p.lab_physician_company_id else None, 'parent=', p.parent_id.name if p.parent_id else '-')

action_domain_docs = env['res.partner'].sudo().search([
    ('is_lab_physician','=',True),
    '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','in', company_ids)
], order='id desc')
print('action domain count=', len(action_domain_docs))
for p in action_domain_docs[:20]:
    print('visible', p.id, p.name)
