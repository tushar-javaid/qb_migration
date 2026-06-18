import frappe

from ..base_importer import BaseImporter


class CustomerImporter(BaseImporter):
    source_type = "QB_CUSTOMER"
    target_doctype = "Customer"
    json_file = "customers.json"
    json_key = "customers"

    def map_record(self, record):
        doc = {
            "doctype": "Customer",
            "customer_name": record["name"],
            "customer_type": "Company" if record.get("is_company") else "Individual",
            "customer_group": "All Customer Groups",
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
