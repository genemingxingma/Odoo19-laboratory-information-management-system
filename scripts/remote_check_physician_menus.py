menus = env['ir.ui.menu'].sudo().search([('name', 'ilike', 'Physician')], order='id asc')
print('menu_count', len(menus))
for m in menus:
    print(m.id, m.complete_name)
    print(' groups:', [g.display_name for g in m.group_ids])

actions = env['ir.actions.act_window'].sudo().search([('name', 'ilike', 'Physician')], order='id asc')
print('action_count', len(actions))
for a in actions:
    print(a.id, a.name, a.res_model)

users = env['res.users'].sudo().search([('login','in',['admin','portal-01@imytest.local','portal-inst-01@imytest.local'])])
for u in users:
    print('user', u.login, 'groups_has_lab_manager=', bool(u.group_ids.filtered(lambda g: g.xml_id=='laboratory_management.group_lab_manager')))
