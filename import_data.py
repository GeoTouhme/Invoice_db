"""
Import Balport_Invoices_Cleaned.csv into PostgreSQL.
Applies schema.sql first, then does a full reload (truncate + import).
Usage: python import_data.py [path/to/file.csv]
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

from csv_importer import import_csv
from db import apply_schema

load_dotenv()

DB_URL = os.environ["DATABASE_URL"]
DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "Balport_Invoices_Cleaned.csv")


def run(csv_path: str = DEFAULT_CSV):
    conn = psycopg2.connect(DB_URL)
    try:
        apply_schema(conn)
    finally:
        conn.close()

    result = import_csv(csv_path, DB_URL, truncate=True)
    print(f"Done. Imported {result['invoices']} invoices and {result['items']} items.")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV)
