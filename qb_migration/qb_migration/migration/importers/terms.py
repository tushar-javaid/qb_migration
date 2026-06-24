import frappe

from ..base_importer import BaseImporter


class TermsImporter(BaseImporter):
    source_type = "QB_PAYMENT_TERM"
    target_doctype = "Payment Term"
    json_file = "terms.json"
    json_key = "terms"

    def get_source_id(self, record):
        return str(record.get("name") or "")

    def _normalize_int(self, value):
        try:
            return int(value)
        except Exception:
            return 0

    def _normalize_float(self, value):
        try:
            return float(value)
        except Exception:
            return 0.0

    def map_record(self, record):
        term_name = (record.get("name") or "").strip()
        if not term_name:
            return {"_skip": True, "_skip_reason": "MISSING_NAME"}

        return {
            "doctype": self.target_doctype,
            "payment_term_name": term_name,
            "credit_days": self._normalize_int(record.get("net_days")),
            "discount_validity": self._normalize_int(record.get("disc_days")),
            "discount": self._normalize_float(record.get("disc_pct")),
            "discount_type": "Percentage",
            "due_date_based_on": "Day(s) after invoice date",
            "discount_validity_based_on": "Day(s) after invoice date",
        }
