login = 'mingxingma@gmail.com'
u = env['res.users'].sudo().search([('login','=',login)], limit=1)
if not u:
    print('user_not_found')
    raise SystemExit

internal_group = env.ref('base.group_user')
portal_group = env.ref('base.group_portal')

if internal_group not in u.group_ids:
    u.write({'group_ids': [(4, internal_group.id)]})
if portal_group in u.group_ids:
    u.write({'group_ids': [(3, portal_group.id)]})

print('after_fix base.group_user=', internal_group in u.group_ids)
print('after_fix base.group_portal=', portal_group in u.group_ids)

# verify physician visibility under this user context
model = env['res.partner'].with_user(u)
domain = [
    ('is_lab_physician','=',True),
    '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','in', u.company_ids.ids)
]
count = model.search_count(domain)
print('visible_physicians=', count)
for p in model.search(domain, limit=10):
    print(p.id, p.name)
