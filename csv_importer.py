"""
Idempotent CSV importer for Balport invoices.
Supports both full reload (truncate) and incremental append/update.
"""

import csv

import psycopg2

from invoice_store import INSERT_ITEM_SQL, UPSERT_INVOICE_SQL

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


def _to_float(val: str | None) -> float | None:
    return float(val) if val and val.strip() else None


def _to_int(val: str | None) -> int | None:
    return int(val) if val and val.strip() else None


def parse_csv(file_path: str) -> tuple[dict[str, tuple], list[tuple]]:
    """Read the CSV once and return (invoices, items).

    invoices maps invoice_number -> tuple in UPSERT_INVOICE_SQL order
    (first row wins for invoice-level fields).
    items is a list of tuples in INSERT_ITEM_SQL order.

    Raises ValueError if required columns are missing.
    """
    invoices: dict[str, tuple] = {}
    items: list[tuple] = []

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        missing = [h for h in REQUIRED_HEADERS if h not in headers]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        for row in reader:
            inv_num = (row["Invoice Number"] or "").strip()
            if not inv_num:
                continue

            if inv_num not in invoices:
                invoices[inv_num] = (
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
                )

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

    return invoices, items


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
    invoices, items = parse_csv(file_path)

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE invoice_items, invoices RESTART IDENTITY CASCADE")
            elif invoices:
                # Idempotency: remove old items for invoices we're re-importing
                cur.execute(
                    "DELETE FROM invoice_items WHERE invoice_number = ANY(%s)",
                    (list(invoices),),
                )

            for inv in invoices.values():
                cur.execute(UPSERT_INVOICE_SQL, inv)

            cur.executemany(INSERT_ITEM_SQL, items)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"invoices": len(invoices), "items": len(items)}
