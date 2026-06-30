import frappe

from ..base_importer import BaseImporter


class PaymentMethodsImporter(BaseImporter):
    source_type = "QB_PAYMENT_METHOD"
    target_doctype = "Mode of Payment"
    json_file = "payment_methods.json"
    json_key = "payment_methods"

    def get_source_id(self, record):
        return str(record.get("list_id") or record.get("name") or "")

    def _map_payment_type(self, payment_type):
        if not payment_type:
            return "General"

        normalized = str(payment_type).strip().lower()
        if normalized == "cash":
            return "Cash"
        if normalized in {"check", "american express", "americanexpress", "discover", "master card", "mastercard", "visa", "echeck", "e-check", "bank"}:
            return "Bank"
        return "General"

    def _resolve_account_by_names(self, names):
        company = frappe.defaults.get_global_default("company")
        for name in names:
            if not name:
                continue
            row = frappe.db.sql(
                "select name from `tabAccount` where company=%s and (lower(name)=lower(%s) or lower(account_name)=lower(%s)) limit 1",
                (company, name, name),
            )
            if row:
                return row[0][0]
        return None

    def _resolve_default_account(self, payment_type):
        return None

    def find_existing_target(self, doc_data):
        mode_name = doc_data.get("mode_of_payment")
        if not mode_name:
            return None
        if frappe.db.exists("Mode of Payment", mode_name):
            return mode_name
        return None

    def map_record(self, record):
        mode_name = record.get("name") or record.get("mode_of_payment")
        if not mode_name:
            return {"_skip": True, "_skip_reason": "MISSING_NAME", "ref_no": record.get("list_id", "")}

        default_account = self._resolve_default_account(record.get("payment_type"))
        account_rows = []
        if default_account:
            account_rows.append({
                "doctype": "Mode of Payment Account",
                "company": frappe.defaults.get_global_default("company"),
                "default_account": default_account,
            })

        return {
            "doctype": "Mode of Payment",
            "mode_of_payment": mode_name,
            "type": self._map_payment_type(record.get("payment_type")),
            "enabled": 1 if record.get("active") else 0,
            "accounts": account_rows,
        }
