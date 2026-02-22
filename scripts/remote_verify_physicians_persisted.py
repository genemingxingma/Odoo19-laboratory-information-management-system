print('sudo_count_persisted', env['res.partner'].sudo().search_count([('is_lab_physician','=',True)]))
u = env['res.users'].sudo().search([('login','=','mingxingma@gmail.com')], limit=1)
dom = [('is_lab_physician','=',True), '|', ('lab_physician_company_id','=',False), ('lab_physician_company_id','in',u.company_ids.ids)]
print('visible_for_user_persisted', env['res.partner'].with_user(u).search_count(dom))
for r in env['res.partner'].with_user(u).search(dom, limit=10):
    print(r.id, r.name)
