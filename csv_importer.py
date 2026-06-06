"""
Idempotent CSV importer for Balport invoices.
Supports both full reload (truncate) and incremental append/update.
"""

import csv
import os

import psycopg2

REQUIRED_HEADERS = [
    "Invoice Date",
    "Invoice Due Date",
    "Process Date",
    "Invoice Number",
    "Invoice Total",
    "Item Count",
    "Vendor Name",
    "Retailer Name",
    "Customer ID",
    "Store ID",
    "Product Number",
    "UPC Number",
    "Pack UPC",
    "Product Description",
    "GL Code",
    "Quantity",
    "Unit Cost",
    "Unit of Measure",
    "Total Adjustments",
    "Total Discount",
    "Extended Price",
    "PPC",
]


def _to_float(val: str) -> float | None:
    return float(val) if val and val.strip() else None


def _to_int(val: str) -> int | None:
    return int(val) if val and val.strip() else None


def import_csv(file_path: str, db_url: str, *, truncate: bool = False) -> dict:
    """
    Import a CSV of Balport invoices into PostgreSQL.

    Parameters
    ----------
    file_path : str
        Path to the CSV file to import.
    db_url : str
        PostgreSQL connection string.
    truncate : bool, optional
        If True, wipes both tables before import (full reload).
        If False, deletes existing line-items for invoices that appear
        in the CSV and then re-inserts (safe incremental update).

    Returns
    -------
    dict
        {"invoices": N, "items": N}
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    # Apply / ensure schema
    with open(schema_path) as f:
        cur.execute(f.read())

    if truncate:
        cur.execute("TRUNCATE invoice_items, invoices RESTART IDENTITY CASCADE")

    invoices_in_csv: set[str] = set()
    items: list[tuple] = []

    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        missing = [h for h in REQUIRED_HEADERS if h not in headers]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        for row in reader:
            inv_num = row["Invoice Number"]
            if not inv_num:
                continue
            invoices_in_csv.add(inv_num)

            items.append(
                (
                    inv_num,
                    row["Product Number"],
                    row["UPC Number"],
                    row["Pack UPC"],
                    row["Product Description"],
                    row["GL Code"],
                    _to_float(row["Quantity"]),
                    _to_float(row["Unit Cost"]),
                    row["Unit of Measure"],
                    _to_float(row["Total Adjustments"]),
                    _to_float(row["Total Discount"]),
                    _to_float(row["Extended Price"]),
                    _to_float(row["PPC"]),
                )
            )

    # --- Idempotency: remove old items for invoices we're about to (re)import ---
    if invoices_in_csv and not truncate:
        cur.execute(
            "DELETE FROM invoice_items WHERE invoice_number = ANY(%s)",
            (list(invoices_in_csv),),
        )

    # --- Insert / update invoices ---
    # We re-read the CSV to get invoice-level data.  Could be optimised by
    # building a dict in the first pass, but for ~10k rows the difference is
    # negligible and this keeps the code simple.
    invoices_seen: set[str] = set()
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            inv_num = row["Invoice Number"]
            if not inv_num or inv_num in invoices_seen:
                continue
            invoices_seen.add(inv_num)

            cur.execute(
                """
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
                """,
                (
                    inv_num,
                    row["Invoice Date"] or None,
                    row["Invoice Due Date"] or None,
                    row["Process Date"] or None,
                    _to_float(row["Invoice Total"]),
                    _to_int(row["Item Count"]),
                    row["Vendor Name"],
                    row["Retailer Name"],
                    row["Customer ID"],
                    row["Store ID"],
                ),
            )

    # --- Insert line items ---
    cur.executemany(
        """
        INSERT INTO invoice_items
            (invoice_number, product_number, upc_number, pack_upc, product_description,
             gl_code, quantity, unit_cost, unit_of_measure, total_adjustments,
             total_discount, extended_price, ppc)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        items,
    )

    conn.commit()
    cur.close()
    conn.close()

    return {"invoices": len(invoices_seen), "items": len(items)}
