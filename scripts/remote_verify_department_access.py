u = env['res.users'].sudo().search([('login','=','mingxingma@gmail.com')], limit=1)
print('user', u.login)
model = env['lab.physician.department'].with_user(u)
print('dept_count_user', model.search_count([]))
for d in model.search([], limit=10):
    print(d.id, d.name)
