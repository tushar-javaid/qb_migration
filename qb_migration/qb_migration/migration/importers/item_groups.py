import frappe
from ..base_importer import BaseImporter

class ItemGroupImporter(BaseImporter):
    source_type = "QB_ITEM_GROUP"
    target_doctype = "Item Group"
    json_file = "item_groups.json"
    json_key = "item_groups"
    allow_missing_file: bool = True

    def load_data(self):
        """
        Override load_data to dynamically derive groups from items.json if item_groups.json is missing.
        """
        try:
            return super().load_data()
        except FileNotFoundError:
            print("  WARN: item_groups.json missing, deriving groups from items.json...")
            # Load items to extract groups
            from .items import ItemImporter
            items = ItemImporter().load_data()
            groups = set()
            for item in items:
                group = item.get("item_group")
                if group:
                    groups.add(group)

            # Format like the original item_groups.json structure
            return [{"name": g, "is_group": 0} for g in sorted(list(groups))]

    def map_record(self, record):
        full_name = record.get("name") or record.get("group_name")
        parts = [part.strip() for part in full_name.split(":") if part.strip()]
        group_name = parts[-1]
        parent_name = parts[-2] if len(parts) > 1 else None

        return {
            "doctype": "Item Group",
            "item_group_name": group_name,
            "parent_item_group": parent_name or "All Item Groups",
            "is_group": record.get("is_group", 0),
        }