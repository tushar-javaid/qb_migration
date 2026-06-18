from ..base_importer import BaseImporter


class ItemGroupImporter(BaseImporter):
    source_type = "QB_ITEM_GROUP"
    target_doctype = "Item Group"
    json_file = "item_groups.json"
    json_key = "item_groups"
    allow_missing_file: bool = True

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
