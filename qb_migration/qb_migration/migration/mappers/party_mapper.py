import frappe


def resolve_customer(qb_name: str):
    return frappe.db.get_value("Customer", {"customer_name": qb_name}, "name")


def resolve_supplier(qb_name: str):
    return frappe.db.get_value("Supplier", {"supplier_name": qb_name}, "name")
