import frappe

from .importers.accounts import AccountImporter
from .importers.item_groups import ItemGroupImporter
from .importers.items import ItemImporter
from .importers.customers import CustomerImporter
from .importers.customer_types import CustomerTypesImporter
from .importers.vendors import SupplierImporter
from .importers.vendor_types import VendorTypesImporter
from .importers.employees import EmployeeImporter
from .importers.purchase_invoices import PurchaseInvoiceImporter
from .importers.purchase_orders import PurchaseOrderImporter
from .importers.payment_methods import PaymentMethodsImporter
from .importers.price_levels import PriceLevelsImporter
from .importers.quantity_discounts import QuantityDiscountImporter
from .importers.terms import TermsImporter
from .importers.bill_payments import BillPaymentImporter
from .importers.deposits import DepositImporter
from .importers.journal_entries import JournalEntryImporter, ChecksImporter
from .importers.payments import PaymentsImporter

PIPELINE = [
    ("accounts", AccountImporter),
    ("item_groups", ItemGroupImporter),
    ("items", ItemImporter),
    ("price_levels", PriceLevelsImporter),
    ("quantity_discounts", QuantityDiscountImporter),
    ("customer_types", CustomerTypesImporter),
    ("customers", CustomerImporter),
    ("vendor_types", VendorTypesImporter),
    ("vendors", SupplierImporter),
    ("employees", EmployeeImporter),
    ("purchase_orders", PurchaseOrderImporter),
    ("purchase_invoices", PurchaseInvoiceImporter),
    ("payment_methods", PaymentMethodsImporter),
    ("terms", TermsImporter),
    ("bill_payments", BillPaymentImporter),
    ("checks", ChecksImporter),
    ("deposits", DepositImporter),
    ("journal_entries", JournalEntryImporter),
    ("payments", PaymentsImporter),
]


def run_migration(stages=None, dry_run=False):
    """Run a migration pipeline from JSON files.

    Execute via bench:
        bench --site <site> execute qb_migration.qb_migration.migration.runner.run_migration
    """
    frappe.flags.in_migrate = True
    frappe.set_user("Administrator")
    results = {}

    for stage_name, ImporterClass in PIPELINE:
        if stages and stage_name not in stages:
            continue

        print(f"\n{'=' * 50}\nRunning stage: {stage_name}\n{'=' * 50}")
        importer = ImporterClass()
        results[stage_name] = importer.run(dry_run=dry_run)

    print("\n\n=== MIGRATION SUMMARY ===")
    for stage, result in results.items():
        print(f"  {stage:25s}: ✓ {result['success']:5d}  ✗ {result['failed']:5d}  ↷ {result['skipped']:5d}")

    return results
