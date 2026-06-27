import frappe

from ..base_importer import BaseImporter


class PriceLevelsImporter(BaseImporter):
    source_type = "QB_PRICE_LEVEL"
    target_doctype = "Price List"
    json_file = "price_levels.json"
    json_key = "price_levels"

    def get_source_id(self, record):
        return str(record.get("name") or "")

    def _map_buying_selling(self, price_level_type):
        normalized = str(price_level_type or "").strip().lower()
        if normalized in {"buying", "buy"}:
            return {"buying": 1, "selling": 0}
        return {"buying": 0, "selling": 1}

    def _get_currency(self):
        company = frappe.defaults.get_global_default("company")
        currency = frappe.db.get_value("Company", company, "default_currency")
        if currency:
            return currency
        return frappe.defaults.get_global_default("currency") or "USD"

    def _resolve_item_code(self, fixed_price):
        candidate = fixed_price.get("item_name") or fixed_price.get("item_list_id")
        if not candidate:
            return None

        item_code = frappe.db.get_value("Item", {"item_code": candidate})
        if item_code:
            return item_code

        item_code = frappe.db.get_value("Item", {"item_name": candidate})
        if item_code:
            return item_code

        return None

    def find_existing_target(self, doc_data):
        return frappe.db.get_value("Price List", {"price_list_name": doc_data.get("price_list_name")})

    def map_record(self, record):
        price_list_name = (record.get("name") or "").strip()
        if not price_list_name:
            return {"_skip": True, "_skip_reason": "MISSING_NAME"}

        flags = self._map_buying_selling(record.get("type"))
        return {
            "doctype": self.target_doctype,
            "price_list_name": price_list_name,
            "enabled": 1,
            **flags,
        }

    def post_insert(self, doc, record):
        fixed_prices = record.get("fixed_prices") or []
        currency = self._get_currency()

        for fixed_price in fixed_prices:
            item_code = self._resolve_item_code(fixed_price)
            if not item_code:
                print(f"  WARN: could not resolve item for fixed price: {fixed_price}")
                continue

            price_list_rate = fixed_price.get("custom_price")
            if price_list_rate is None:
                price_list_rate = fixed_price.get("custom_pct")

            if price_list_rate is None:
                print(f"  WARN: skipped fixed price without rate for item {item_code}")
                continue

            existing = frappe.db.get_value(
                "Item Price",
                {
                    "price_list": doc.price_list_name,
                    "item_code": item_code,
                    "currency": currency,
                },
                "name",
            )
            if existing:
                continue

            item_price = frappe.get_doc(
                {
                    "doctype": "Item Price",
                    "price_list": doc.price_list_name,
                    "item_code": item_code,
                    "price_list_rate": price_list_rate,
                    "currency": currency,
                }
            )
            item_price.flags.ignore_permissions = True
            item_price.insert()
