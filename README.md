# Invoice DB — Balport Invoice Tracker

A Flask + PostgreSQL web app for tracking liquor-store vendor invoices:

- **Product search** — filter line items by name, UPC, department, vendor, and date range
- **Invoice detail** pages
- **CSV import** — idempotent bulk import (re-uploading an invoice updates it, no duplicates)
- **PDF import with AI extraction** — upload a vendor PDF, the text is parsed by an LLM
  (Anthropic Claude or a local Ollama model) into a review form you can correct before saving
- **Stats API** (`/api/stats`) — totals by department, vendor, month, and top products

## Requirements

- Python 3.10+
- PostgreSQL 13+

## Local setup

```bash
git clone https://github.com/GeoTouhme/Invoice_db
cd Invoice_db
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Create a database and apply the schema:

```bash
createdb balport
psql -d balport -f schema.sql
```

> The schema tries to create trigram (`pg_trgm`) indexes so product/UPC search stays
> fast on large tables. If your DB user isn't superuser it skips them with a notice;
> to get them, run `CREATE EXTENSION pg_trgm;` once as superuser, then re-apply
> `schema.sql`.

Configure the environment:

```bash
cp .env.example .env
# edit .env — at minimum set DATABASE_URL, SECRET_KEY, and APP_PASSWORD
```

Run the app:

```bash
flask --app app run --debug
# open http://127.0.0.1:5000
```

## Configuration (.env)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | PostgreSQL connection string |
| `SECRET_KEY` | production | Flask session signing key — set to a long random string |
| `APP_USERNAME` / `APP_PASSWORD` | production | Login credentials. **If `APP_PASSWORD` is empty, the app runs without any authentication.** |
| `ANTHROPIC_API_KEY` | optional | Enables Claude for PDF extraction (best accuracy) |
| `ANTHROPIC_MODEL` | optional | Defaults to `claude-haiku-4-5` |
| `OLLAMA_URL` / `OLLAMA_MODEL` / `OLLAMA_API_KEY` | optional | Fallback local/remote Ollama for PDF extraction |
| `DB_POOL_MAX` | optional | Max DB connections per worker (default 5) |

Without any LLM configured, PDF upload still works — you just fill the review form manually.

## Importing data

**Web:** *Upload CSV* in the navbar. The required column headers are listed on that page.
Re-importing an existing invoice replaces its line items instead of duplicating them.

**CLI (full reload):**

```bash
python import_data.py path/to/invoices.csv   # truncates and re-imports everything
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for a full Ubuntu VPS guide (PostgreSQL + gunicorn + nginx + HTTPS).
In production make sure you set `SECRET_KEY` and `APP_PASSWORD`.

## Migrating an existing database

`schema.sql` uses `CREATE TABLE IF NOT EXISTS`, so it won't change tables created by an
older version. If you set up the database before the FK/constraint changes, run once:

```sql
ALTER TABLE invoice_items ALTER COLUMN invoice_number SET NOT NULL;
ALTER TABLE invoice_items DROP CONSTRAINT invoice_items_invoice_number_fkey;
ALTER TABLE invoice_items
    ADD CONSTRAINT invoice_items_invoice_number_fkey
    FOREIGN KEY (invoice_number) REFERENCES invoices(invoice_number) ON DELETE CASCADE;
```

Then re-apply `schema.sql` to pick up the new indexes.

## Project layout

```
app.py             Flask routes (search, invoice detail, uploads, auth, stats API)
db.py              Connection pool + query helper + schema applier
invoice_store.py   Shared invoice upsert SQL (used by CSV and PDF paths)
csv_importer.py    Idempotent CSV parser/importer
pdf_extractor.py   PDF → text (PyMuPDF)
llm_extractor.py   Text → structured invoice JSON (Claude → Ollama fallback)
import_data.py     CLI full-reload importer
schema.sql         Tables + indexes
templates/, static/
tests/
```
