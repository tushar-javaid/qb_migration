import frappe
import json
from frappe.utils import flt

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
        # Prefer Customer, then Supplier, then Employee
        for doctype in ("Customer", "Supplier", "Employee"):
            if frappe.db.exists(doctype, entity):
                return doctype, entity

        # Try to create Customer or Employee if they don't exist
        # Prefer creating Customer for party-like names
        customer = self._ensure_customer(entity)
        if customer:
            return "Customer", customer

        employee = self._ensure_employee(entity)
        if employee:
            return "Employee", employee

        return None, None

    def _ensure_customer(self, customer_name):
        if not customer_name:
            return None

        if frappe.db.exists("Customer", customer_name):
            return customer_name

        try:
            from .customers import CustomerImporter

            importer = CustomerImporter()
            group = importer._get_or_create_safe_leaf_group()

            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": customer_name,
                    "customer_group": group,
                    "territory": "All Territories",
                }
            )
            customer.flags.ignore_permissions = True
            customer.insert()
            frappe.db.commit()
            return customer.name
        except Exception:
            frappe.db.rollback()
            return None

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

    def _resolve_cost_center(self, cc_name):
        """Resolve a QuickBooks class/cost center name to an ERPNext Cost Center name.

        Returns the Cost Center `name` if found, otherwise `None`.
        """
        if not cc_name:
            return None

        company = frappe.defaults.get_global_default("company")
        leaf = cc_name.split(":")[-1].strip()

        # Try exact cost_center_name match
        name = frappe.db.get_value("Cost Center", {"cost_center_name": leaf, "company": company}, "name")
        if name:
            return name

        # Try case-insensitive match
        row = frappe.db.sql(
            "select name from `tabCost Center` where lower(cost_center_name)=lower(%s) and company=%s limit 1",
            (leaf, company),
        )
        if row:
            return row[0][0]

        # Try matching by document name (some installs store the same value in name)
        if frappe.db.exists("Cost Center", leaf):
            return leaf

        # Try full name case-insensitive
        row = frappe.db.sql(
            "select name from `tabCost Center` where lower(cost_center_name)=lower(%s) and company=%s limit 1",
            (cc_name, company),
        )
        if row:
            return row[0][0]

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
                # Try common fields for party/entity, falling back to record payee
                candidate = (
                    line.get("entity")
                    or line.get("customer")
                    or line.get("customer_name")
                    or line.get("party")
                    or record.get("payee")
                )
                # If the account suggests employee advances, prefer/reserve Employee party first
                acct_name_lower = (erpnext_account or "").lower()
                if candidate and ("employee" in acct_name_lower or "advance" in acct_name_lower):
                    emp = self._ensure_employee(candidate)
                    if emp:
                        party_type, party = "Employee", emp
                    else:
                        party_type, party = self._resolve_party(candidate)
                else:
                    party_type, party = self._resolve_party(candidate)

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


class ChecksImporter(JournalEntryImporter):
    """
    Map QuickBooks expense checks (checks.json) to ERPNext Journal Entries.
    Each check becomes one Bank Entry – debit expense lines, credit the bank account.
    """
    source_type = "QB_CHECK"
    target_doctype = "Journal Entry"
    json_file = "checks.json"
    json_key = "checks"

    def get_source_id(self, record):
        return str(record.get("txn_id") or "")

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")

        # Bank account to credit
        bank_account = self._resolve_account(record.get("bank_account"))
        if not bank_account:
            raise ValueError(
                f"Bank account not found: {record.get('bank_account')} "
                f"(check {record.get('ref_no')})"
            )

        posting_date = self.normalize_date(record.get("date"))
        cheque_no = (record.get("ref_no") or record.get("ref_number", ""))
        # Treat obvious non-numeric placeholders as empty (e.g. 'DRAFT')
        if isinstance(cheque_no, str) and cheque_no.strip().upper() == "DRAFT":
            cheque_no = ""
        accounts = []
        total = 0.0

        for line in record.get("lines") or []:
            account = self._resolve_account(line.get("account"))
            if not account:
                continue

            amount = flt(line.get("amount", 0))
            if not amount:
                continue

            row = {
                "account": account,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
                "debit": amount,
                "credit": 0,
                "exchange_rate": 1,
                "user_remark": line.get("memo") or line.get("description", ""),
            }

            # Resolve cost center (QuickBooks 'class_name') if present
            cost_center = self._resolve_cost_center(line.get("class_name"))
            if cost_center:
                row["cost_center"] = cost_center

            # If account is Receivable/Payable, resolve party
            account_type = frappe.db.get_value("Account", account, "account_type")
            if account_type in ("Receivable", "Payable"):
                candidate = (
                    line.get("entity")
                    or line.get("customer")
                    or line.get("customer_name")
                    or line.get("party")
                    or record.get("payee")
                )
                acct_name_lower = (account or "").lower()
                if candidate and ("employee" in acct_name_lower or "advance" in acct_name_lower):
                    emp = self._ensure_employee(candidate)
                    if emp:
                        party_type, party = "Employee", emp
                    else:
                        party_type, party = self._resolve_party(candidate)
                else:
                    party_type, party = self._resolve_party(candidate)
                if party_type and party:
                    row["party_type"] = party_type
                    row["party"] = party

            accounts.append(row)
            total += amount

        if total <= 0:
            return {"_skip": True, "_skip_reason": "ZERO_AMOUNT", "ref_no": cheque_no}

        # Single credit to the bank
        accounts.append({
            "account": bank_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": total,
            "debit": 0,
            "credit": total,
            "exchange_rate": 1,
            "user_remark": record.get("memo") or f"Payee: {record.get('payee', '')}",
        })

        # Ensure Bank Entry has reference_no & reference_date (some setups require it)
        reference_no = cheque_no or record.get("txn_id") or record.get("ref_no") or ""
        cheque_no_field = cheque_no or reference_no
        doc = {
            "doctype": "Journal Entry",
            "voucher_type": "Bank Entry",
            "company": company,
            "posting_date": posting_date,
            "cheque_no": cheque_no_field,
            "reference_no": reference_no,
            "reference_date": posting_date,
            "cheque_date": posting_date,
            "user_remark": record.get("memo") or f"Check to {record.get('payee', '')}",
            "accounts": accounts,
        }

        # Debug helper: print generated doc for a failing txn so we can inspect party/account mapping
        if str(record.get("txn_id")) == "DD3-933784469":
            try:
                print("DEBUG_GENERATED_DOC for DD3-933784469:")
                print(json.dumps(doc, default=str))
            except Exception:
                print("DEBUG: failed to dump doc for", record.get("txn_id"))

        return doc

    def find_existing_target(self, doc_data):
        """Avoid duplicates by looking up existing Journal Entry with same cheque no & date."""
        if doc_data.get("cheque_no"):
            return frappe.db.get_value(
                "Journal Entry",
                {
                    "cheque_no": doc_data["cheque_no"],
                    "company": doc_data.get("company"),
                    "posting_date": doc_data.get("posting_date"),
                },
                "name",
            )
        return None