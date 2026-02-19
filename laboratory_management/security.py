from __future__ import annotations

import frappe

ROLE_LIMS_MANAGER = "LIMS Manager"
ROLE_LIMS_SAMPLER = "LIMS Sampler"
ROLE_LIMS_ANALYST = "LIMS Analyst"
ROLE_LIMS_VERIFIER = "LIMS Verifier"
ROLE_SYSTEM_MANAGER = "System Manager"


def has_any_role(*roles: str) -> bool:
	user_roles = set(frappe.get_roles(frappe.session.user))
	return any(role in user_roles for role in roles)


def ensure_roles(*roles: str):
	if has_any_role(ROLE_SYSTEM_MANAGER, ROLE_LIMS_MANAGER):
		return
	if not has_any_role(*roles):
		frappe.throw(f"Permission denied. Required role: {', '.join(roles)}")
