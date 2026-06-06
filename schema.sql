-- Balport Invoices Database Schema

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
    invoice_number      TEXT REFERENCES invoices(invoice_number),
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
