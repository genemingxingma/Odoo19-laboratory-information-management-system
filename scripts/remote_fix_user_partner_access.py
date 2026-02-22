login = 'mingxingma@gmail.com'
u = env['res.users'].sudo().search([('login','=',login)], limit=1)
if not u:
    print('user_not_found')
    raise SystemExit

for xid in ['base.group_user', 'base.group_partner_manager']:
    g = env.ref(xid)
    if g not in u.group_ids:
        u.write({'group_ids': [(4, g.id)]})

model = env['res.partner'].with_user(u)
print('search_count_all_partners=', model.search_count([]))
domain = [('is_lab_physician','=',True),'|',('lab_physician_company_id','=',False),('lab_physician_company_id','in',u.company_ids.ids)]
print('search_count_physicians=', model.search_count(domain))
for p in model.search(domain, limit=10):
    print(p.id, p.name)
