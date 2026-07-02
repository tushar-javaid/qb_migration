import frappe
from frappe.utils import flt

from .journal_entries import JournalEntryImporter


class TransfersImporter(JournalEntryImporter):
    source_type = "QB_TRANSFER"
    target_doctype = "Payment Entry"
    json_file = "transfers.json"
    json_key = "transfers"

    def get_source_id(self, record):
        return str(record.get("txn_id") or record.get("txn_number") or "")

    def _resolve_mode_of_payment(self, mode):
        if mode:
            existing = frappe.db.get_value("Mode of Payment", {"mode_of_payment": mode}, "name")
            if existing:
                return existing

        existing = frappe.db.get_value("Mode of Payment", {}, "name")
        if existing:
            return existing

        mode_name = mode or "Bank"
        doc = frappe.get_doc({
            "doctype": "Mode of Payment",
            "mode_of_payment": mode_name,
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()
        return doc.name

    def find_existing_target(self, doc_data):
        if doc_data.get("reference_no"):
            return frappe.db.get_value(
                "Payment Entry",
                {
                    "reference_no": doc_data["reference_no"],
                    "company": doc_data.get("company"),
                    "payment_type": "Internal Transfer",
                },
                "name",
            )
        return None

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")
        amount = flt(record.get("amount", 0) or 0)
        if amount <= 0:
            return {"_skip": True, "_skip_reason": "ZERO_AMOUNT", "ref_no": record.get("txn_number") or record.get("txn_id")}

        from_account = self._resolve_account(record.get("from_account"))
        to_account = self._resolve_account(record.get("to_account"))
        if not from_account or not to_account:
            return {
                "_skip": True,
                "_skip_reason": "NO_VALID_ACCOUNT",
                "ref_no": record.get("txn_number") or record.get("txn_id"),
            }

        posting_date = self.normalize_date(record.get("date") or record.get("txn_date"))
        reference_no = record.get("txn_id") or record.get("txn_number") or ""

        doc_data = {
            "doctype": "Payment Entry",
            "payment_type": "Internal Transfer",
            "company": company,
            "posting_date": posting_date,
            "reference_no": reference_no,
            "reference_date": posting_date,
            "paid_from": from_account,
            "paid_to": to_account,
            "paid_amount": amount,
            "received_amount": amount,
            "remarks": record.get("memo") or "Funds Transfer",
        }

        payment_method = (record.get("payment_method") or record.get("method") or "").strip()
        if payment_method:
            doc_data["mode_of_payment"] = self._resolve_mode_of_payment(payment_method)

        return doc_data
