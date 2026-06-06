"""
Import Balport_Invoices_Cleaned.csv into PostgreSQL.
Usage: python import_data.py
"""

import csv
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.environ["DATABASE_URL"]
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "Balport_Invoices_Cleaned.csv")


def run():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # Apply schema
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        cur.execute(f.read())

    invoices_seen = set()
    items = []

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            inv_num = int(row["Invoice Number"])

            if inv_num not in invoices_seen:
                invoices_seen.add(inv_num)
                cur.execute(
                    """
                    INSERT INTO invoices
                        (invoice_number, invoice_date, invoice_due_date, process_date,
                         invoice_total, item_count, vendor_name, retailer_name,
                         customer_id, store_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (invoice_number) DO NOTHING
                    """,
                    (
                        inv_num,
                        row["Invoice Date"] or None,
                        row["Invoice Due Date"] or None,
                        row["Process Date"] or None,
                        float(row["Invoice Total"]) if row["Invoice Total"] else None,
                        int(row["Item Count"]) if row["Item Count"] else None,
                        row["Vendor Name"],
                        row["Retailer Name"],
                        int(row["Customer ID"]) if row["Customer ID"] else None,
                        row["Store ID"],
                    ),
                )

            items.append((
                inv_num,
                row["Product Number"],
                row["UPC Number"],
                row["Pack UPC"],
                row["Product Description"],
                row["GL Code"],
                float(row["Quantity"]) if row["Quantity"] else None,
                float(row["Unit Cost"]) if row["Unit Cost"] else None,
                row["Unit of Measure"],
                float(row["Total Adjustments"]) if row["Total Adjustments"] else None,
                float(row["Total Discount"]) if row["Total Discount"] else None,
                float(row["Extended Price"]) if row["Extended Price"] else None,
                float(row["PPC"]) if row["PPC"] else None,
            ))

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
    print(f"Done. Imported {len(invoices_seen)} invoices and {len(items)} items.")


if __name__ == "__main__":
    run()
