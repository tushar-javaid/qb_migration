import frappe

from ..base_importer import BaseImporter


class JournalEntryImporter(BaseImporter):
    source_type = "QB_JOURNAL"
    target_doctype = "Journal Entry"
    json_file = "journal_entries.json"
    json_key = "journal_entries"

    def get_source_id(self, record):
        return str(record.get("txn_id") or "")

    def _resolve_account(self, qb_account_name):
        if not qb_account_name:
            return None

        company = frappe.defaults.get_global_default("company")
        leaf = qb_account_name.split(":")[-1].strip()

        account = frappe.db.get_value(
            "Account",
            {"account_name": leaf, "company": company, "is_group": 0},
            "name",
        )
        if account:
            return account

        def resolve_group_child(account_name):
            row = frappe.db.sql(
                "select name from `tabAccount` where parent_account=%s and company=%s and is_group=0 limit 1",
                (account_name, company),
            )
            return row[0][0] if row else None

        row = frappe.db.sql(
            "select name, is_group from `tabAccount` where account_name=%s and company=%s limit 1",
            (leaf, company),
        )
        if row:
            name, is_group = row[0]
            if not is_group:
                return name
            return resolve_group_child(name)

        row = frappe.db.sql(
            "select name, is_group from `tabAccount` where lower(account_name)=lower(%s) and company=%s limit 1",
            (leaf, company),
        )
        if row:
            name, is_group = row[0]
            if not is_group:
                return name
            return resolve_group_child(name)

        row = frappe.db.sql(
            "select name, is_group from `tabAccount` where lower(account_name)=lower(%s) and company=%s limit 1",
            (qb_account_name, company),
        )
        if row:
            name, is_group = row[0]
            if not is_group:
                return name
            return resolve_group_child(name)

        return None

    def _resolve_party(self, entity):
        if not entity:
            return None, None

        for doctype in ("Employee", "Supplier", "Customer"):
            if frappe.db.exists(doctype, entity):
                return doctype, entity

        employee = self._ensure_employee(entity)
        if employee:
            return "Employee", employee

        return None, None

    def _ensure_employee(self, employee_name):
        if frappe.db.exists("Employee", employee_name):
            return employee_name

        try:
            employee = frappe.get_doc(
                {
                    "doctype": "Employee",
                    "employee_name": employee_name,
                    "status": "Active",
                }
            )
            employee.flags.ignore_permissions = True
            employee.insert()
            frappe.db.commit()
            return employee.name
        except Exception:
            frappe.db.rollback()
            return None

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        accounts = []

        currency = record.get("currency")
        exchange_rate = record.get("exchange_rate")

        is_foreign_currency = bool(currency and currency != company_currency)
        is_multi_currency = is_foreign_currency and bool(exchange_rate)

        for line in record.get("lines", []):
            acct_name = line.get("account", "")
            erpnext_account = self._resolve_account(acct_name)
            if not erpnext_account:
                raise ValueError(f"Account not found: {acct_name}")

            # Get the actual currency of this account
            account_currency = frappe.db.get_value("Account", erpnext_account, "account_currency")
            amount = line.get("amount", 0) or 0
            line_type = (line.get("line_type") or "").strip().lower()

            if line_type == "debit":
                debit_val = amount
                credit_val = 0
            elif line_type == "credit":
                debit_val = 0
                credit_val = amount
            else:
                debit_val = line.get("debit", 0) or 0
                credit_val = line.get("credit", 0) or 0

            # ---- Multi-currency handling ----
            if is_multi_currency:
                if account_currency == company_currency:
                    # Company currency account: amount in account currency is the converted value
                    acct_ccy_debit = debit_val * exchange_rate
                    acct_ccy_credit = credit_val * exchange_rate
                    base_debit = acct_ccy_debit
                    base_credit = acct_ccy_credit
                    row_exchange_rate = 1.0
                else:
                    # Foreign currency account (assumed to match transaction currency)
                    acct_ccy_debit = debit_val
                    acct_ccy_credit = credit_val
                    base_debit = debit_val * exchange_rate
                    base_credit = credit_val * exchange_rate
                    row_exchange_rate = exchange_rate
            else:
                # Single currency (all amounts are in company currency)
                acct_ccy_debit = debit_val
                acct_ccy_credit = credit_val
                base_debit = debit_val
                base_credit = credit_val
                row_exchange_rate = 1.0

            party_type = party = None
            account_type = frappe.db.get_value("Account", erpnext_account, "account_type")
            if account_type in ("Receivable", "Payable"):
                party_type, party = self._resolve_party(line.get("entity"))

            row_data = {
                "account": erpnext_account,
                "debit": base_debit,
                "credit": base_credit,
                "debit_in_account_currency": acct_ccy_debit,
                "credit_in_account_currency": acct_ccy_credit,
                "exchange_rate": row_exchange_rate,
                "user_remark": line.get("memo", ""),
            }
            if party_type and party:
                row_data["party_type"] = party_type
                row_data["party"] = party

            accounts.append(row_data)

        doc = {
            "doctype": "Journal Entry",
            "voucher_type": "Journal Entry",
            "posting_date": self.normalize_date(record.get("txn_date")),
            "company": company,
            "user_remark": record.get("memo", ""),
            "accounts": accounts,
        }

        if is_multi_currency:
            doc["multi_currency"] = 1
            doc["currency"] = currency
            doc["exchange_rate"] = exchange_rate

        return doc
