for login in ['admin','portal-01@imytest.local','portal-inst-01@imytest.local']:
    u = env['res.users'].sudo().search([('login','=',login)], limit=1)
    if not u:
        print(login, 'not found')
        continue
    print(login, 'share=', u.share, 'groups=', ', '.join(u.group_ids.mapped('display_name')[:8]))
