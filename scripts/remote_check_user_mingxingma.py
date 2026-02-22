login = 'mingxingma@gmail.com'
u = env['res.users'].sudo().search([('login', '=', login)], limit=1)
if not u:
    print('not_found')
else:
    print('id=', u.id, 'name=', u.name, 'active=', u.active, 'share=', u.share)
    print('company_id=', u.company_id.id, u.company_id.name)
    print('company_ids=', u.company_ids.ids)
    print('groups_count=', len(u.group_ids))
    # print key groups
    targets = [
        'base.group_user',
        'base.group_portal',
        'laboratory_management.group_lab_user',
        'laboratory_management.group_lab_reception',
        'laboratory_management.group_lab_analyst',
        'laboratory_management.group_lab_reviewer',
        'laboratory_management.group_lab_manager',
    ]
    imd = env['ir.model.data'].sudo()
    for xid in targets:
        module, name = xid.split('.')
        rec = imd.search([('module','=',module),('name','=',name)], limit=1)
        if rec and rec.model == 'res.groups':
            gid = rec.res_id
            print(xid, '=>', bool(u.group_ids.filtered(lambda g: g.id == gid)))
        else:
            print(xid, '=> group_missing')
