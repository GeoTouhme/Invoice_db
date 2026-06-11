"""Shared SQL for writing invoices, used by both the CSV importer and the
PDF review flow so the upsert logic lives in exactly one place."""

UPSERT_INVOICE_SQL = """
    INSERT INTO invoices
        (invoice_number, invoice_date, invoice_due_date, process_date,
         invoice_total, item_count, vendor_name, retailer_name,
         customer_id, store_id)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (invoice_number) DO UPDATE SET
        invoice_date      = EXCLUDED.invoice_date,
        invoice_due_date  = EXCLUDED.invoice_due_date,
        process_date      = EXCLUDED.process_date,
        invoice_total     = EXCLUDED.invoice_total,
        item_count        = EXCLUDED.item_count,
        vendor_name       = EXCLUDED.vendor_name,
        retailer_name     = EXCLUDED.retailer_name,
        customer_id       = EXCLUDED.customer_id,
        store_id          = EXCLUDED.store_id
"""

INSERT_ITEM_SQL = """
    INSERT INTO invoice_items
        (invoice_number, product_number, upc_number, pack_upc, product_description,
         gl_code, quantity, unit_cost, unit_of_measure, total_adjustments,
         total_discount, extended_price, ppc)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""

DELETE_ITEMS_SQL = "DELETE FROM invoice_items WHERE invoice_number = %s"


def invoice_tuple(inv: dict) -> tuple:
    """Order matches UPSERT_INVOICE_SQL placeholders."""
    return (
        inv["invoice_number"],
        inv.get("invoice_date") or None,
        inv.get("invoice_due_date") or None,
        inv.get("process_date") or None,
        inv.get("invoice_total"),
        inv.get("item_count"),
        inv.get("vendor_name"),
        inv.get("retailer_name"),
        inv.get("customer_id"),
        inv.get("store_id"),
    )


def item_tuple(invoice_number: str, item: dict) -> tuple:
    """Order matches INSERT_ITEM_SQL placeholders."""
    return (
        invoice_number,
        item.get("product_number"),
        item.get("upc_number"),
        item.get("pack_upc"),
        item.get("product_description"),
        item.get("gl_code"),
        item.get("quantity"),
        item.get("unit_cost"),
        item.get("unit_of_measure"),
        item.get("total_adjustments") or 0,
        item.get("total_discount") or 0,
        item.get("extended_price"),
        item.get("ppc"),
    )


def replace_invoice(cur, inv: dict, items: list[dict]) -> None:
    """Upsert one invoice and replace all of its line items (idempotent)."""
    cur.execute(UPSERT_INVOICE_SQL, invoice_tuple(inv))
    cur.execute(DELETE_ITEMS_SQL, (inv["invoice_number"],))
    for item in items:
        cur.execute(INSERT_ITEM_SQL, item_tuple(inv["invoice_number"], item))
