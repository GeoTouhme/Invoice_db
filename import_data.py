"""
Import Balport_Invoices_Cleaned.csv into PostgreSQL.
Usage: python import_data.py
"""

import os

from dotenv import load_dotenv

from csv_importer import import_csv

load_dotenv()

DB_URL = os.environ["DATABASE_URL"]
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "Balport_Invoices_Cleaned.csv")


def run():
    result = import_csv(CSV_PATH, DB_URL, truncate=True)
    print(f"Done. Imported {result['invoices']} invoices and {result['items']} items.")


if __name__ == "__main__":
    run()
