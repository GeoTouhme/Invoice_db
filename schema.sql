-- Balport Invoices Database Schema
--
-- NOTE: this file uses CREATE ... IF NOT EXISTS, so it is safe to re-run,
-- but it will NOT alter tables that already exist. If you created the
-- database with an older version of this schema, see the migration
-- snippet in README.md.

CREATE TABLE IF NOT EXISTS invoices (
    invoice_number      TEXT PRIMARY KEY,
    invoice_date        DATE,
    invoice_due_date    DATE,
    process_date        DATE,
    invoice_total       NUMERIC(12, 2),
    item_count          INTEGER,
    vendor_name         TEXT,
    retailer_name       TEXT,
    customer_id         TEXT,
    store_id            TEXT
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id                  SERIAL PRIMARY KEY,
    invoice_number      TEXT NOT NULL REFERENCES invoices(invoice_number) ON DELETE CASCADE,
    product_number      TEXT,
    upc_number          TEXT,
    pack_upc            TEXT,
    product_description TEXT,
    gl_code             TEXT,
    quantity            NUMERIC(10, 2),
    unit_cost           NUMERIC(10, 2),
    unit_of_measure     TEXT,
    total_adjustments   NUMERIC(10, 2),
    total_discount      NUMERIC(10, 2),
    extended_price      NUMERIC(10, 2),
    ppc                 NUMERIC(10, 2)
);

CREATE INDEX IF NOT EXISTS idx_items_invoice   ON invoice_items(invoice_number);
CREATE INDEX IF NOT EXISTS idx_items_gl_code   ON invoice_items(gl_code);
CREATE INDEX IF NOT EXISTS idx_items_product   ON invoice_items(product_number);
CREATE INDEX IF NOT EXISTS idx_invoices_vendor ON invoices(vendor_name);
CREATE INDEX IF NOT EXISTS idx_invoices_date   ON invoices(invoice_date);

-- Trigram indexes so the ILIKE '%term%' searches on the main page can use
-- an index instead of scanning the whole table. Requires the pg_trgm
-- extension; creating an extension usually needs superuser, so this block
-- degrades gracefully when the app user lacks the privilege.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
    CREATE INDEX IF NOT EXISTS idx_items_desc_trgm
        ON invoice_items USING gin (product_description gin_trgm_ops);
    CREATE INDEX IF NOT EXISTS idx_items_upc_trgm
        ON invoice_items USING gin (upc_number gin_trgm_ops);
    CREATE INDEX IF NOT EXISTS idx_items_pack_upc_trgm
        ON invoice_items USING gin (pack_upc gin_trgm_ops);
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'pg_trgm extension not available (needs superuser) - skipping trigram indexes. Run once as superuser: CREATE EXTENSION pg_trgm; then re-apply this schema.';
END $$;
