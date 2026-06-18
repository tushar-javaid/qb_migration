import frappe

from ..base_importer import BaseImporter

QB_ACCOUNT_TYPE_MAP = {
    "Bank": ("Bank", "Asset"),
    "AccountsReceivable": ("Receivable", "Asset"),
    "AccountsPayable": ("Payable", "Liability"),
    "CreditCard": ("Liability", "Liability"),
    "Income": ("Income Account", "Income"),
    "Expense": ("Expense Account", "Expense"),
    "CostOfGoodsSold": ("Cost of Goods Sold", "Expense"),
    "FixedAsset": ("Fixed Asset", "Asset"),
    "OtherCurrentAsset": ("Current Asset", "Asset"),
    "OtherCurrentLiability": ("Liability", "Liability"),
    "OtherAsset": ("Current Asset", "Asset"),
    "Equity": ("Equity", "Equity"),
    "LongTermLiability": ("Liability", "Liability"),
    "OtherIncome": ("Income Account", "Income"),
    "OtherExpense": ("Expense Account", "Expense"),
}

DEFAULT_PARENT_GROUPS = {
    "Bank": "Bank Accounts",
    "AccountsReceivable": "Current Assets",
    "AccountsPayable": "Current Liabilities",
    "CreditCard": "Current Liabilities",
    "Income": "Income",
    "OtherIncome": "Income",
    "Expense": "Expenses",
    "CostOfGoodsSold": "Stock Expenses",
    "OtherExpense": "Expenses",
    "FixedAsset": "Fixed Assets",
    "OtherCurrentAsset": "Current Assets",
    "OtherAsset": "Current Assets",
    "OtherCurrentLiability": "Current Liabilities",
    "Equity": "Equity",
    "LongTermLiability": "Non-Current Liabilities",
}

ROOT_TYPE_GROUPS = {
    "Asset": "Current Assets",
    "Liability": "Current Liabilities",
    "Income": "Income",
    "Expense": "Expenses",
    "Equity": "Equity",
}


class AccountImporter(BaseImporter):
    source_type = "QB_ACCOUNT"
    target_doctype = "Account"
    json_file = "accounts.json"
    json_key = "accounts"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parent_groups = None

    @property
    def parent_groups(self):
        if self._parent_groups is None:
            self._parent_groups = set()
            for record in self.load_data():
                full_name = record.get("full_name") or record.get("name")
                parts = [part.strip() for part in full_name.split(":") if part.strip()]
                for idx in range(1, len(parts)):
                    self._parent_groups.add(":".join(parts[:idx]))
        return self._parent_groups

    def _find_account(self, account_name, company):
        if not account_name:
            return None

        account_name = account_name.strip()
        name = frappe.db.get_value(
            "Account",
            {"account_name": account_name, "company": company},
            "name",
        )
        if name:
            return name

        row = frappe.db.sql(
            "select name from `tabAccount` where lower(account_name)=lower(%s) and company=%s limit 1",
            (account_name, company),
        )
        return row[0][0] if row else None

    def _default_parent_name(self, qb_type, root_type):
        return DEFAULT_PARENT_GROUPS.get(qb_type) or ROOT_TYPE_GROUPS.get(root_type)

    def _ensure_account_group(self, account_name, qb_type, root_type, company):
        if not account_name:
            return None

        existing = self._find_account(account_name, company)
        if existing:
            return existing

        parent_name = self._default_parent_name(qb_type, root_type)
        parent_account = self._find_account(parent_name, company) if parent_name else None

        doc = frappe.get_doc({
            "doctype": "Account",
            "account_name": account_name,
            "company": company,
            "parent_account": parent_account,
            "account_type": QB_ACCOUNT_TYPE_MAP.get(qb_type, ("Expense Account", root_type))[0],
            "root_type": root_type,
            "is_group": 1,
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()
        return doc.name

    def find_existing_target(self, doc_data):
        return self._find_account(doc_data.get("account_name"), doc_data.get("company"))

    def _resolve_parent_account(self, parent_name, qb_type, root_type, company, full_name):
        if not parent_name:
            return None

        existing_parent = self._find_account(parent_name, company)
        if existing_parent:
            parent_doc = frappe.get_doc("Account", existing_parent)
            if parent_doc.is_group:
                return existing_parent

            if full_name in self.parent_groups:
                fallback = f"{parent_name} (QB Group)"
                existing_fallback = self._find_account(fallback, company)
                if existing_fallback:
                    return existing_fallback
                return self._ensure_account_group(
                    fallback,
                    qb_type,
                    root_type,
                    company,
                    parent_account=self._find_account(self._default_parent_name(qb_type, root_type), company),
                )

            return parent_doc.parent_account

        return self._ensure_account_group(parent_name, qb_type, root_type, company)

    def _ensure_account_group(self, account_name, qb_type, root_type, company, parent_account=None):
        if not account_name:
            return None

        existing = self._find_account(account_name, company)
        if existing:
            existing_doc = frappe.get_doc("Account", existing)
            if existing_doc.is_group:
                return existing
            return None

        if not parent_account:
            parent_name = self._default_parent_name(qb_type, root_type)
            parent_account = self._find_account(parent_name, company)

        doc = frappe.get_doc({
            "doctype": "Account",
            "account_name": account_name,
            "company": company,
            "parent_account": parent_account,
            "account_type": QB_ACCOUNT_TYPE_MAP.get(qb_type, ("Expense Account", root_type))[0],
            "root_type": root_type,
            "is_group": 1,
        })
        doc.flags.ignore_permissions = True
        doc.insert()
        frappe.db.commit()
        return doc.name

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")
        qb_type = record.get("account_type", "Expense")
        acct_type, root_type = QB_ACCOUNT_TYPE_MAP.get(
            qb_type, ("Expense Account", "Expense")
        )

        full_name = record.get("full_name") or record.get("name")
        if qb_type == "NonPosting":
            return None

        parts = [part.strip() for part in full_name.split(":") if part.strip()]
        account_name = parts[-1]
        parent_name = parts[-2] if len(parts) > 1 else record.get("parent")

        parent_account = self._resolve_parent_account(parent_name, qb_type, root_type, company, full_name)

        if not parent_account:
            default_parent_name = self._default_parent_name(qb_type, root_type)
            parent_account = self._find_account(default_parent_name, company)

        is_group = 1 if full_name in self.parent_groups else int(record.get("is_group", 0))

        return {
            "doctype": "Account",
            "account_name": account_name,
            "account_type": acct_type,
            "root_type": root_type,
            "company": company,
            "parent_account": parent_account,
            "is_group": is_group,
        }
