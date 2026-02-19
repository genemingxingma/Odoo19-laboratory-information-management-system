# laboratory_management

SENAITE-inspired Laboratory Information Management System (LIMS) for ERPNext/Frappe.

## Deployment Rule

- Local machine is the single source of truth for code.
- Do not edit application code directly on server.
- Do not run manual SQL on server database.
- Deploy only from local package to server, then run framework migration.

## Remote Deploy

Use:

```bash
bash scripts/deploy_remote.sh
```

Default target:

- host: `192.168.10.190`
- user: `mamingxing`
- bench: `/home/frappe/frappe-bench`
- site: `erp.imytest.com`
