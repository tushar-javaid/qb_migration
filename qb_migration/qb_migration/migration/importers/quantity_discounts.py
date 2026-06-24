import frappe

from ..base_importer import BaseImporter


class QuantityDiscountImporter(BaseImporter):
    source_type = "QB_QUANTITY_DISCOUNT"
    target_doctype = "Pricing Rule"
    json_file = "quantity_discounts.json"
    json_key = "quantity_discounts"

    def map_record(self, record):
        discount_pct = record.get("discount_pct", 0)
        discount_rate = record.get("discount_rate", 0)

        # Determine the discount type and value
        discount_type = "Price Discount" if record.get("discount_rate") else "Percentage"
        discount_value = discount_rate if discount_rate else discount_pct

        doc = {
            "doctype": "Pricing Rule",
            "title": record.get("item_name", "Pricing Rule"),
            "description": record.get("description", ""),
            "disabled": 0 if record.get("active") else 1,
            "discount_type": discount_type,
            "discount_percentage": discount_pct if discount_type == "Percentage" else 0,
            "discount_amount": discount_rate if discount_type == "Price Discount" else 0,
            "apply_on": "Transaction",
            "priority": 1,
        }

        return doc
