import frappe

from ..base_importer import BaseImporter


class CustomerTypesImporter(BaseImporter):
    source_type = "QB_CUSTOMER_TYPE"
    target_doctype = "Customer Group"
    json_file = "customer_types.json"
    json_key = "customer_types"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent_names = None

    def get_source_id(self, record):
        return str(record.get("list_id") or "")

    def _get_root_group(self):
        root = frappe.db.get_value(
            "Customer Group",
            {"is_group": 1, "parent_customer_group": ["is", "not set"]},
            "name",
        )
        if root:
            return root
        root = frappe.db.get_value(
            "Customer Group",
            {"is_group": 1, "parent_customer_group": ""},
            "name",
        )
        return root or "All Customer Groups"

    def _get_parent_names(self):
        if self._parent_names is None:
            self._parent_names = set(
                (record.get("parent") or "").strip()
                for record in self.load_data()
                if (record.get("parent") or "").strip()
            )
        return self._parent_names

    def _normalize_disabled(self, active_value):
        return 0 if active_value else 1

    def _ensure_group(self, group_name, parent_name=None, is_group=True, disabled=0):
        if not group_name:
            return None

        group_name = group_name.strip()
        if not group_name:
            return None

        existing = frappe.db.get_value(
            "Customer Group",
            {"customer_group_name": group_name},
            "name",
        )
        if existing:
            doc = frappe.get_doc("Customer Group", existing)
            if is_group and int(doc.is_group or 0) == 0:
                doc.is_group = 1
            if parent_name and doc.parent_customer_group != parent_name:
                doc.parent_customer_group = parent_name
            if int(doc.disabled or 0) != int(disabled or 0):
                doc.disabled = disabled
            if doc.is_modified():
                doc.flags.ignore_permissions = True
                doc.save(ignore_permissions=True)
            return existing

        if not parent_name:
            parent_name = self._get_root_group()

        doc = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": group_name,
                "parent_customer_group": parent_name,
                "is_group": 1 if is_group else 0,
                "disabled": disabled,
            }
        )
        doc.flags.ignore_permissions = True
        doc.insert()
        return doc.name

    def find_existing_target(self, doc_data):
        return frappe.db.get_value(
            "Customer Group",
            {"customer_group_name": doc_data.get("customer_group_name")},
            "name",
        )

    def map_record(self, record):
        group_name = (record.get("name") or "").strip()
        if not group_name:
            return {"_skip": True, "_skip_reason": "MISSING_NAME"}

        parent_name = (record.get("parent") or "").strip()
        disabled = self._normalize_disabled(record.get("active", True))

        parent_group = None
        if parent_name:
            parent_group = self._ensure_group(parent_name, is_group=True, disabled=0)

        is_group = group_name in self._get_parent_names()
        return {
            "doctype": self.target_doctype,
            "customer_group_name": group_name,
            "parent_customer_group": parent_group or self._get_root_group(),
            "is_group": 1 if is_group else 0,
            "disabled": disabled,
        }
