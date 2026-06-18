import frappe


def get_erp_account_name(qb_account_name: str, company: str):
    if not qb_account_name:
        return None

    leaf = qb_account_name.split(":")[-1].strip()
    return frappe.db.get_value(
        "Account", {"account_name": leaf, "company": company}, "name"
    )
