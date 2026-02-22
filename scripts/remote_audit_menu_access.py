from odoo.exceptions import AccessError, MissingError, UserError

login = 'mingxingma@gmail.com'
user = env['res.users'].sudo().search([('login', '=', login)], limit=1)
if not user:
    print('ERROR: user not found', login)
    raise SystemExit(1)

imd = env['ir.model.data'].sudo()
menu_imd = imd.search([('module', '=', 'laboratory_management'), ('model', '=', 'ir.ui.menu')])
menus = env['ir.ui.menu'].sudo().browse(menu_imd.mapped('res_id')).sorted(lambda m: (m.complete_name, m.id))

print('AUDIT_USER', user.login, 'ID', user.id)
print('TOTAL_MODULE_MENUS', len(menus))

ok = []
fail = []
skip = []

for menu in menus:
    action = menu.action
    if not action:
        skip.append((menu.complete_name, 'no_action'))
        continue
    if action._name != 'ir.actions.act_window':
        skip.append((menu.complete_name, 'action_type_%s' % action._name))
        continue

    model_name = action.res_model
    if not model_name:
        fail.append((menu.complete_name, 'missing_res_model'))
        continue

    try:
        model = env[model_name].with_user(user)
        # access rights + lightweight read probe
        model.check_access('read')
        model.search_count([])
        ok.append((menu.complete_name, model_name))
    except Exception as exc:
        fail.append((menu.complete_name, model_name, str(exc).split('\n')[0]))

print('OK_COUNT', len(ok))
print('FAIL_COUNT', len(fail))
print('SKIP_COUNT', len(skip))

if fail:
    print('--- FAILURES ---')
    for item in fail:
        print('FAIL', item)

if skip:
    print('--- SKIPPED (first 40) ---')
    for item in skip[:40]:
        print('SKIP', item)
