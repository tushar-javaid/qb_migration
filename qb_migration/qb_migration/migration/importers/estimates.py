import frappe

from ..base_importer import BaseImporter


class EstimateImporter(BaseImporter):
    source_type = "QB_ESTIMATE"
    target_doctype = "Quotation"
    json_file = "estimates.json"
    json_key = "estimates"

    def get_source_id(self, record):
        return str(record.get("txn_id") or record.get("ref_no") or "")

    def get_or_create_customer_group(self):
        root = frappe.db.get_value(
            "Customer Group",
            {"is_group": 1, "parent_customer_group": ["is", "not set"]},
            "name",
        )
        if not root:
            root = frappe.db.get_value(
                "Customer Group",
                {"is_group": 1, "parent_customer_group": ""},
                "name",
            )
        if not root:
            root = "All Customer Groups"

        existing = frappe.db.get_value(
            "Customer Group",
            {"customer_group_name": "QuickBooks Customers", "parent_customer_group": root},
            "name",
        )
        if existing:
            return existing

        group = frappe.get_doc({
            "doctype": "Customer Group",
            "customer_group_name": "QuickBooks Customers",
            "parent_customer_group": root,
            "is_group": 0,
        })
        group.flags.ignore_permissions = True
        group.insert()
        frappe.db.commit()
        return group.name

    def get_or_create_item_group(self):
        root = frappe.db.get_value(
            "Item Group",
            {"is_group": 1, "parent_item_group": ["is", "not set"]},
            "name",
        )
        if not root:
            root = frappe.db.get_value(
                "Item Group",
                {"is_group": 1, "parent_item_group": ""},
                "name",
            )
        if not root:
            root = "All Item Groups"

        existing = frappe.db.get_value(
            "Item Group",
            {"item_group_name": "QuickBooks Items", "parent_item_group": root},
            "name",
        )
        if existing:
            return existing

        group = frappe.get_doc({
            "doctype": "Item Group",
            "item_group_name": "QuickBooks Items",
            "parent_item_group": root,
            "is_group": 0,
        })
        group.flags.ignore_permissions = True
        group.insert()
        frappe.db.commit()
        return group.name

    def resolve_customer(self, qb_customer_name):
        if not qb_customer_name:
            raise ValueError("Customer name missing on estimate record")

        customer = frappe.db.get_value("Customer", {"customer_name": qb_customer_name}, "name")
        if customer:
            return customer

        result = frappe.db.sql(
            "select name from `tabCustomer` where lower(customer_name)=lower(%s) limit 1",
            qb_customer_name,
        )
        if result:
            return result[0][0]

        new_customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": qb_customer_name,
            "customer_type": "Individual",
            "customer_group": self.get_or_create_customer_group(),
            "territory": "All Territories",
        })
        new_customer.flags.ignore_permissions = True
        new_customer.insert()
        frappe.db.commit()
        return new_customer.name

    def resolve_item(self, qb_item_name):
        if not qb_item_name:
            raise ValueError("Item name missing on estimate line")

        item = frappe.db.get_value("Item", {"item_code": qb_item_name}, ["name", "item_code", "item_name"])
        if item:
            return item[1] or item[0], item[2] or item[1] or item[0]

        result = frappe.db.sql(
            "select name, item_code, item_name from `tabItem` where lower(item_code)=lower(%s) limit 1",
            qb_item_name,
        )
        if result:
            name, item_code, item_name = result[0]
            return item_code or name, item_name or item_code or name

        new_item = frappe.get_doc({
            "doctype": "Item",
            "item_code": qb_item_name,
            "item_name": qb_item_name,
            "description": qb_item_name,
            "item_group": self.get_or_create_item_group(),
            "stock_uom": "Nos",
            "is_stock_item": 0,
            "is_purchase_item": 1,
            "is_sales_item": 1,
        })
        new_item.flags.ignore_permissions = True
        new_item.insert()
        frappe.db.commit()
        return new_item.item_code, new_item.item_name

    def resolve_sales_partner(self, salesman):
        if not salesman:
            return None

        partner = frappe.db.get_value("Sales Partner", {"partner_name": salesman}, "name")
        if partner:
            return partner

        result = frappe.db.sql(
            "select name from `tabSales Partner` where lower(partner_name)=lower(%s) limit 1",
            salesman,
        )
        if result:
            return result[0][0]

        new_partner = frappe.get_doc({
            "doctype": "Sales Partner",
            "partner_name": salesman,
            "commission_rate": 0,
            "enabled": 1,
        })
        new_partner.flags.ignore_permissions = True
        new_partner.insert()
        frappe.db.commit()
        return new_partner.name

    def resolve_payment_terms_template(self, terms):
        if not terms:
            return None

        template = frappe.db.get_value("Payment Terms Template", {"name": terms}, "name")
        if template:
            return template

        return None

    def post_insert(self, doc, source_record):
        if getattr(doc, "doctype", None) == "Quotation" and doc.docstatus == 0:
            doc.submit()
            frappe.db.commit()

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")
        customer = self.resolve_customer(record.get("cust_name"))

        items = []
        for idx, line in enumerate(record.get("lines", []), 1):
            item_name = line.get("item") or line.get("item_name") or ""
            if not item_name and not line.get("description"):
                continue

            if item_name:
                item_code, item_name_value = self.resolve_item(item_name)
            else:
                item_code, item_name_value = None, None

            qty = line.get("qty") or line.get("quantity") or 1
            try:
                qty = int(float(qty))
            except (TypeError, ValueError):
                qty = 1

            item_name_text = item_name_value or line.get("description") or item_name or ""
            if len(item_name_text) > 140:
                item_name_text = item_name_text[:137] + "..."

            items.append({
                "idx": idx,
                "item_code": item_code,
                "item_name": item_name_text,
                "qty": qty,
                "uom": line.get("unitms") or "Nos",
                "rate": line.get("price") or line.get("rate") or 0,
                "amount": line.get("ext_price") or line.get("amount") or 0,
                "description": line.get("description") or "",
            })

        if not items:
            raise ValueError("No valid item lines found for estimate")

        doc = {
            "doctype": "Quotation",
            "quotation_to": "Customer",
            "party_name": customer,
            "transaction_date": self.normalize_date(record.get("date")),
            "valid_till": self.normalize_date(record.get("due_date") or record.get("date")),
            "company": company,
            "po_no": record.get("ref_no") or record.get("po_num") or "",
            "customer_note": record.get("memo") or "",
            "items": items,
        }

        sales_partner = self.resolve_sales_partner(record.get("salesman"))
        if sales_partner:
            doc["sales_partner"] = sales_partner

        payment_terms_template = self.resolve_payment_terms_template(record.get("terms"))
        if payment_terms_template:
            doc["payment_terms_template"] = payment_terms_template

        return doc
