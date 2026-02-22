recs = env['res.partner'].sudo().search([('is_lab_physician','=',True)])
print('sudo physicians=', len(recs))
for r in recs:
    print(r.id, r.name, 'company_id=', r.company_id.id if r.company_id else None, 'lab_physician_company_id=', r.lab_physician_company_id.id if r.lab_physician_company_id else None)
