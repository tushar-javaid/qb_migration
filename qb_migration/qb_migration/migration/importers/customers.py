import frappe

from ..base_importer import BaseImporter


class CustomerImporter(BaseImporter):
    source_type = "QB_CUSTOMER"
    target_doctype = "Customer"
    json_file = "customers.json"
    json_key = "customers"

    def resolve_customer_group(self, qb_group_name):
        if not qb_group_name:
            return "All Customers"

        # Find the group node
        group = frappe.db.get_value("Customer Group", {"customer_group_name": qb_group_name}, "name")

        # Check if it is a group
        if group and frappe.db.get_value("Customer Group", group, "is_group"):
            # If it is a group, find or create a leaf node under it
            leaf_name = f"{qb_group_name} - Leaf"
            existing_leaf = frappe.db.get_value("Customer Group", {"customer_group_name": leaf_name}, "name")
            if existing_leaf:
                return existing_leaf

            # Create leaf
            new_leaf = frappe.get_doc({
                "doctype": "Customer Group",
                "customer_group_name": leaf_name,
                "parent_customer_group": qb_group_name,
                "is_group": 0
            })
            new_leaf.flags.ignore_permissions = True
            new_leaf.insert()
            frappe.db.commit()
            return new_leaf.name

        return group or "All Customers"

    def map_record(self, record):
        doc = {
            "doctype": "Customer",
            "customer_name": record["name"],
            "customer_type": "Company" if record.get("is_company") else "Individual",
            "customer_group": self.resolve_customer_group(record.get("customer_group")),
            "territory": "All Territories",
        }

        if record.get("address"):
            doc["_address"] = record["address"]

        return doc

    def post_insert(self, doc, source_record):
        address = source_record.get("_address")
        if not address:
            return

        frappe.get_doc({
            "doctype": "Address",
            "address_type": "Billing",
            "address_line1": address.get("line1", ""),
            "city": address.get("city", ""),
            "state": address.get("state", ""),
            "pincode": address.get("zip", ""),
            "country": address.get("country", "United States"),
            "links": [{"link_doctype": "Customer", "link_name": doc.name}],
        }).insert(ignore_permissions=True)
