import frappe

from ..base_importer import BaseImporter

QB_ITEM_TYPE_MAP = {
    "INV": "Stock Item",
    "SVC": "Service Item",
    "NON": "Non Stock Item",
    "GRPITEM": "Service Item",
    "OTHCHG": "Service Item",
}


class ItemImporter(BaseImporter):
    source_type = "QB_ITEM"
    target_doctype = "Item"
    json_file = "items.json"
    json_key = "items"

    def resolve_account(self, qb_name):
        if not qb_name:
            return None

        leaf = qb_name.split(":")[-1].strip()
        company = frappe.defaults.get_global_default("company")
        return frappe.db.get_value(
            "Account", {"account_name": leaf, "company": company}, "name"
        )

    def find_existing_target(self, doc_data):
        return frappe.db.get_value("Item", {"item_code": doc_data.get("item_code")}, "name")

    def resolve_item_group(self, item_group_name):
        if not item_group_name:
            return "All Item Groups"

        item_group_name = item_group_name.strip()
        existing = frappe.db.get_value(
            "Item Group", {"item_group_name": item_group_name}, "name"
        )
        if existing:
            return existing

        fallback = frappe.db.sql(
            "select name from `tabItem Group` where lower(item_group_name)=lower(%s) limit 1",
            item_group_name,
        )
        if fallback:
            return fallback[0][0]

        doc = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": item_group_name,
            "parent_item_group": "All Item Groups",
            "is_group": 0,
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()
        return doc.name

    def map_record(self, record):
        item_type = QB_ITEM_TYPE_MAP.get(record.get("item_type", "SVC"), "Service Item")
        is_stock = item_type == "Stock Item"
        company = frappe.defaults.get_global_default("company")

        doc = {
            "doctype": "Item",
            "item_code": record["item"],
            "item_name": record["item"],
            "description": record.get("description") or record["item"],
            "item_group": self.resolve_item_group(record.get("item_group")),
            "stock_uom": record.get("stock_uom", "Nos"),
            "is_stock_item": 1 if is_stock else 0,
            "is_purchase_item": 1,
            "is_sales_item": 1,
            "valuation_rate": record.get("cost", 0),
            "standard_rate": record.get("price", 0),
        }

        income_acct = self.resolve_account(record.get("income_acct"))
        cogs_acct = self.resolve_account(record.get("cogs_acct"))
        asset_acct = self.resolve_account(record.get("asset_acct"))

        if income_acct or cogs_acct or asset_acct:
            doc["item_defaults"] = [
                {
                    "company": company,
                    "income_account": income_acct,
                    "expense_account": cogs_acct,
                    "asset_account": asset_acct if is_stock else None,
                }
            ]

        return doc
