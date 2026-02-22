login='mingxingma@gmail.com'
u = env['res.users'].sudo().search([('login','=',login)], limit=1)
print('user', u.id, u.login)
model = env['ir.model']._get('res.partner')
rules = env['ir.rule'].sudo().search([('model_id','=',model.id),('perm_read','=',True)])
print('all read rules for res.partner:', len(rules))
for r in rules:
    # rule applies if no groups or intersects user groups
    applies = (not r.groups) or bool(r.groups & u.group_ids)
    if applies:
        print('APPLY', r.id, r.name, 'global=', not bool(r.groups), 'groups=', [g.display_name for g in r.groups], 'domain=', r.domain_force)

# try count with sudo and with user for same simple domains
sudo_model = env['res.partner'].sudo()
usr_model = env['res.partner'].with_user(u)
for dom,label in [
    ([('is_lab_physician','=',True)], 'is_lab_physician'),
    ([('is_lab_physician','=',True),('lab_physician_company_id','=',1)], 'physician_company=1'),
    ([('is_lab_physician','=',True),('company_id','=',1)], 'partner_company=1'),
    ([('is_lab_physician','=',True),('company_id','=',False)], 'partner_company=False'),
]:
    print(label, 'sudo=', sudo_model.search_count(dom), 'user=', usr_model.search_count(dom))
