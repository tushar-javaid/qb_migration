import frappe

from ..base_importer import BaseImporter


class BillPaymentImporter(BaseImporter):
    source_type = "QB_BILL_PAYMENT"
    target_doctype = "Payment Entry"
    json_file = "bill_payments.json"
    json_key = "bill_payments"

    def get_source_id(self, record):
        return str(record.get("txn_id") or record.get("ref_number") or "")

    def _resolve_account(self, qb_account_name):
        if not qb_account_name:
            return None
        leaf = qb_account_name.split(":")[-1].strip()
        company = frappe.defaults.get_global_default("company")
        return frappe.db.get_value(
            "Account", {"account_name": leaf, "company": company}, "name"
        )

    def _resolve_payable_account(self):
        company = frappe.defaults.get_global_default("company")
        account = frappe.db.get_value(
            "Account",
            {
                "account_type": "Payable",
                "root_type": "Liability",
                "company": company,
                "is_group": 0,
            },
            "name",
        )
        if account:
            return account

        row = frappe.db.sql(
            "select name from `tabAccount` where account_type='Payable' and root_type='Liability' and company=%s and is_group=0 limit 1",
            (company,),
        )
        return row[0][0] if row else None

    def _resolve_payment_account(self, qb_account_name=None):
        company = frappe.defaults.get_global_default("company")
        if qb_account_name:
            leaf = qb_account_name.split(":")[-1].strip()
            account = frappe.db.get_value(
                "Account",
                {"account_name": leaf, "company": company, "is_group": 0},
                "name",
            )
            if account:
                return account

            row = frappe.db.sql(
                "select name, is_group from `tabAccount` where account_name=%s and company=%s limit 1",
                (leaf, company),
            )
            if row:
                name, is_group = row[0]
                if not is_group:
                    return name
                child = frappe.db.sql(
                    "select name from `tabAccount` where parent_account=%s and company=%s and is_group=0 limit 1",
                    (name, company),
                )
                if child:
                    return child[0][0]

        row = frappe.db.sql(
            "select name from `tabAccount` where account_type='Bank' and root_type='Asset' and company=%s and is_group=0 limit 1",
            (company,),
        )
        if row:
            return row[0][0]

        row = frappe.db.sql(
            "select name from `tabAccount` where account_type='Cash' and root_type='Asset' and company=%s and is_group=0 limit 1",
            (company,),
        )
        return row[0][0] if row else None

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

    def resolve_purchase_invoice(self, bill_no, supplier_name=None, amount=None):
        if bill_no:
            result = frappe.db.get_value("Purchase Invoice", {"bill_no": bill_no}, "name")
            if not result:
                result = frappe.db.sql(
                    "select name from `tabPurchase Invoice` where lower(bill_no)=lower(%s) limit 1",
                    bill_no,
                )
                result = result[0][0] if result else None
            if result:
                return result

        if supplier_name and amount is not None:
            result = frappe.db.sql(
                "select name from `tabPurchase Invoice` where supplier=%s and abs(grand_total - %s) < 0.01 order by bill_date desc limit 1",
                (supplier_name, amount),
            )
            if result:
                return result[0][0]

        return None

    def find_existing_target(self, doc_data):
        if doc_data.get("reference_no"):
            return frappe.db.get_value(
                "Payment Entry",
                {
                    "reference_no": doc_data["reference_no"],
                    "party": doc_data.get("party"),
                    "company": doc_data.get("company"),
                },
                "name",
            )
        return None

    def map_record(self, record):
        company = frappe.defaults.get_global_default("company")
        payment_account = self._resolve_payment_account(
            record.get("account") or record.get("payment_account") or record.get("bank_account")
        )
        bill_no = None
        if record.get("applied"):
            bill_no = record.get("applied")[0].get("ref_no")
        if not bill_no:
            bill_no = record.get("bill_no") or record.get("ref_no")

        payment_amount = record.get("total_amt", record.get("amount", 0)) or 0
        if not payment_amount and record.get("applied"):
            payment_amount = sum(item.get("amount", 0) or 0 for item in record.get("applied", []))

        paid_to_invoice = self.resolve_purchase_invoice(
            bill_no,
            record.get("vend_name") or record.get("vendor"),
            payment_amount,
        )

        if paid_to_invoice:
            outstanding_amount = frappe.db.get_value(
                "Purchase Invoice",
                paid_to_invoice,
                "outstanding_amount",
            )
            if outstanding_amount is not None and float(outstanding_amount) == 0:
                return {
                    "_skip": True,
                    "_skip_reason": "ALREADY_PAID",
                    "ref_no": record.get("ref_no", ""),
                }

        if not payment_amount:
            return {
                "_skip": True,
                "_skip_reason": "ZERO_AMOUNT",
                "ref_no": record.get("ref_no", ""),
            }

        payable_account = self._resolve_payable_account()
        payment_account = payment_account or self._resolve_payment_account()
        if not payable_account or not payment_account:
            return {
                "_skip": True,
                "_skip_reason": "NO_VALID_ACCOUNT",
                "ref_no": record.get("ref_no", ""),
            }

        supplier = record.get("vend_name") or record.get("vendor")
        if paid_to_invoice:
            invoice_supplier = frappe.db.get_value("Purchase Invoice", paid_to_invoice, "supplier")
            if invoice_supplier:
                supplier = invoice_supplier

        references = []
        if paid_to_invoice:
            references.append(
                {
                    "reference_doctype": "Purchase Invoice",
                    "reference_name": paid_to_invoice,
                    "allocated_amount": payment_amount,
                }
            )

        return {
            "doctype": "Payment Entry",
            "payment_type": "Pay",
            "company": company,
            "posting_date": self.normalize_date(record.get("date") or record.get("txn_date")),
            "mode_of_payment": self._resolve_mode_of_payment(record.get("payment_method")),
            "party_type": "Supplier",
            "party": supplier,
            "party_account": payable_account,
            "reference_no": record.get("ref_no", ""),
            "reference_date": self.normalize_date(record.get("date") or record.get("txn_date")),
            "paid_amount": payment_amount,
            "received_amount": payment_amount,
            "paid_from": payment_account,
            "paid_to": payable_account,
            "references": references,
        }
