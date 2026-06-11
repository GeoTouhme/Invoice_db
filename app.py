import hmac
import logging
import os
import secrets
import tempfile

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.exceptions import RequestEntityTooLarge

from csv_importer import import_csv
from db import connection, query
from invoice_store import replace_invoice
from llm_extractor import extract_invoice_data
from pdf_extractor import extract_text_from_pdf

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

_secret = os.environ.get("SECRET_KEY")
if not _secret:
    # Random per-process key: sessions/flash still work, but won't survive a
    # restart and won't be shared between gunicorn workers. Set SECRET_KEY!
    _secret = secrets.token_hex(32)
    log.warning("SECRET_KEY is not set; using a random per-process key. "
                "Set SECRET_KEY in production.")
app.secret_key = _secret

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload cap

csrf = CSRFProtect(app)

# ── Authentication ────────────────────────────────────────────────────────────
# Single-user auth via env vars. If APP_PASSWORD is unset, auth is disabled
# (convenient for local dev) and a warning is logged.

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

if not APP_PASSWORD:
    log.warning("APP_PASSWORD is not set; the app is accessible without login. "
                "Set APP_USERNAME / APP_PASSWORD in production.")

_PUBLIC_ENDPOINTS = {"login", "static"}


@app.before_request
def require_login():
    if not APP_PASSWORD:
        return
    if request.endpoint in _PUBLIC_ENDPOINTS:
        return
    if session.get("logged_in"):
        return
    next_url = request.full_path.rstrip("?") if request.method == "GET" else None
    return redirect(url_for("login", next=next_url))


@app.route("/login", methods=["GET", "POST"])
def login():
    if not APP_PASSWORD:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user_ok = hmac.compare_digest(username, APP_USERNAME)
        pass_ok = hmac.compare_digest(password, APP_PASSWORD)
        if user_ok and pass_ok:
            session["logged_in"] = True
            target = request.args.get("next", "")
            # Only follow same-site relative paths to avoid open redirects
            if not target.startswith("/") or target.startswith("//"):
                target = url_for("index")
            return redirect(target)
        flash("Invalid username or password", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out", "success")
    return redirect(url_for("login"))


@app.context_processor
def inject_auth():
    return {"auth_enabled": bool(APP_PASSWORD)}


# ── Error handlers ────────────────────────────────────────────────────────────

@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_exc):
    flash("File is too large (max 16 MB)", "danger")
    return redirect(request.referrer or url_for("index"))


@app.errorhandler(CSRFError)
def handle_csrf_error(exc):
    flash(f"Form session expired, please try again ({exc.description})", "danger")
    return redirect(request.referrer or url_for("index"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _paginate(page, per_page=50):
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    return page, per_page, (page - 1) * per_page


def _parse_num(raw, label, errors, *, required=False, default=None,
               as_int=False):
    """Parse a number from form input, tolerating $ signs and thousands
    separators. Appends a message to `errors` instead of raising."""
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        if required:
            errors.append(f"{label} is required")
        return default
    try:
        return int(raw) if as_int else float(raw)
    except ValueError:
        errors.append(f"{label}: '{raw}' is not a valid number")
        return default


def _save_upload(uploaded, suffix):
    """Persist an uploaded file to a unique temp path (safe under multiple
    gunicorn workers, works on Windows too). Caller must delete it."""
    fd, path = tempfile.mkstemp(prefix="balport_upload_", suffix=suffix)
    os.close(fd)
    uploaded.save(path)
    return path


# ── Products search (main page) ───────────────────────────────────────────────

@app.route("/")
def index():
    page, per_page, offset = _paginate(request.args.get("page", 1))

    upc         = request.args.get("upc", "").strip()
    name        = request.args.get("name", "").strip()
    department  = request.args.get("department", "").strip()
    date_from   = request.args.get("date_from", "").strip()
    date_to     = request.args.get("date_to", "").strip()
    vendor      = request.args.get("vendor", "").strip()

    where, params = ["1=1"], []

    if upc:
        where.append("(ii.upc_number ILIKE %s OR ii.pack_upc ILIKE %s)")
        like = f"%{upc}%"
        params += [like, like]
    if name:
        where.append("ii.product_description ILIKE %s")
        params.append(f"%{name}%")
    if department:
        where.append("ii.gl_code = %s")
        params.append(department)
    if vendor:
        where.append("i.vendor_name = %s")
        params.append(vendor)
    if date_from:
        where.append("i.invoice_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("i.invoice_date <= %s")
        params.append(date_to)

    where_sql = " AND ".join(where)

    base_sql = """
        FROM invoice_items ii
        JOIN invoices i ON i.invoice_number = ii.invoice_number
        WHERE """ + where_sql

    total = query(f"SELECT COUNT(*) AS n {base_sql}", params, one=True)["n"]

    products = query(
        f"""SELECT
                ii.product_number,
                ii.upc_number,
                ii.product_description,
                ii.gl_code            AS department,
                ii.quantity,
                ii.unit_of_measure,
                ii.unit_cost,
                ii.total_adjustments,
                ii.total_discount,
                ii.extended_price,
                i.invoice_number,
                i.invoice_date,
                i.vendor_name
            {base_sql}
            ORDER BY i.invoice_date DESC, ii.product_description
            LIMIT %s OFFSET %s""",
        params + [per_page, offset],
    )

    departments = [r["gl_code"] for r in query(
        "SELECT DISTINCT gl_code FROM invoice_items ORDER BY gl_code")]
    vendors = [r["vendor_name"] for r in query(
        "SELECT DISTINCT vendor_name FROM invoices ORDER BY vendor_name")]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "index.html",
        products=products,
        page=page,
        total_pages=total_pages,
        total=total,
        departments=departments,
        vendors=vendors,
        filters=dict(upc=upc, name=name, department=department,
                     vendor=vendor, date_from=date_from, date_to=date_to),
    )


# ── Invoice detail ────────────────────────────────────────────────────────────

@app.route("/invoice/<path:invoice_number>")
def invoice_detail(invoice_number):
    inv = query("SELECT * FROM invoices WHERE invoice_number = %s",
                (invoice_number,), one=True)
    if not inv:
        abort(404)

    items = query(
        """SELECT product_number, upc_number, product_description, gl_code,
                  quantity, unit_cost, unit_of_measure,
                  total_adjustments, total_discount, extended_price
           FROM invoice_items
           WHERE invoice_number = %s
           ORDER BY gl_code, product_description""",
        (invoice_number,),
    )
    return render_template("invoice.html", inv=inv, items=items)


# ── Stats API ─────────────────────────────────────────────────────────────────

@app.route("/api/stats")
def stats():
    by_dept = query(
        """SELECT gl_code AS department,
                  COUNT(*)            AS lines,
                  SUM(quantity)       AS total_qty,
                  SUM(extended_price) AS total_cost
           FROM invoice_items
           GROUP BY gl_code ORDER BY total_cost DESC""")

    by_vendor = query(
        """SELECT vendor_name,
                  COUNT(*)          AS invoices,
                  SUM(invoice_total) AS total
           FROM invoices GROUP BY vendor_name ORDER BY total DESC""")

    monthly = query(
        """SELECT TO_CHAR(invoice_date,'YYYY-MM') AS month,
                  SUM(invoice_total) AS total
           FROM invoices GROUP BY month ORDER BY month""")

    top_products = query(
        """SELECT product_description, gl_code,
                  SUM(quantity)       AS total_qty,
                  SUM(extended_price) AS total_cost
           FROM invoice_items
           GROUP BY product_description, gl_code
           ORDER BY total_cost DESC LIMIT 20""")

    return jsonify({
        "by_department": [dict(r) for r in by_dept],
        "by_vendor":     [dict(r) for r in by_vendor],
        "monthly":       [dict(r) for r in monthly],
        "top_products":  [dict(r) for r in top_products],
    })


# ── CSV Upload ────────────────────────────────────────────────────────────────

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or uploaded.filename == "":
            flash("No file selected", "danger")
            return redirect(url_for("upload"))

        if not uploaded.filename.lower().endswith(".csv"):
            flash("Only CSV files are allowed", "danger")
            return redirect(url_for("upload"))

        temp_path = _save_upload(uploaded, ".csv")
        try:
            result = import_csv(temp_path, os.environ["DATABASE_URL"], truncate=False)
            flash(
                f"Import successful: {result['invoices']} invoices and {result['items']} items",
                "success",
            )
        except ValueError as exc:
            flash(f"File error: {exc}", "danger")
        except Exception:
            log.exception("CSV import failed")
            flash("Unexpected error during import — check the server logs", "danger")
        finally:
            os.unlink(temp_path)

        return redirect(url_for("upload"))

    return render_template("upload.html")


# ── PDF Upload ────────────────────────────────────────────────────────────────

EMPTY_INVOICE = {
    "invoice_number": "",
    "invoice_date": "",
    "invoice_due_date": "",
    "process_date": "",
    "invoice_total": "",
    "item_count": "",
    "vendor_name": "",
    "retailer_name": "Balport Liquor Store",
    "customer_id": "",
    "store_id": "000001",
    "line_items": [],
}


@app.route("/upload-pdf", methods=["GET", "POST"])
def upload_pdf():
    if request.method == "POST":
        uploaded = request.files.get("file")
        if not uploaded or uploaded.filename == "":
            flash("No file selected", "danger")
            return redirect(url_for("upload_pdf"))

        if not uploaded.filename.lower().endswith(".pdf"):
            flash("Only PDF files are allowed", "danger")
            return redirect(url_for("upload_pdf"))

        temp_path = _save_upload(uploaded, ".pdf")
        try:
            raw_text = extract_text_from_pdf(temp_path)
        except Exception:
            log.exception("PDF text extraction failed")
            flash("Failed to extract text from PDF", "danger")
            return redirect(url_for("upload_pdf"))
        finally:
            os.unlink(temp_path)

        # Optional AI auto-fill; falls back to an empty form
        ai_data = extract_invoice_data(raw_text)
        data = ai_data if ai_data else dict(EMPTY_INVOICE)

        return render_template("review_pdf.html", raw_text=raw_text, data=data)

    return render_template("upload_pdf.html")


def _form_to_invoice():
    """Rebuild the invoice dict + line items from the review form.
    Returns (inv, line_items, errors). Numeric fields are parsed leniently
    and problems are collected instead of raising."""
    errors: list[str] = []

    inv = {
        "invoice_number": request.form.get("inv_invoice_number", "").strip(),
        "invoice_date": request.form.get("inv_invoice_date", "").strip() or None,
        "invoice_due_date": request.form.get("inv_invoice_due_date", "").strip() or None,
        "process_date": request.form.get("inv_process_date", "").strip() or None,
        "invoice_total": _parse_num(request.form.get("inv_invoice_total"),
                                    "Invoice Total", errors),
        "item_count": _parse_num(request.form.get("inv_item_count"),
                                 "Item Count", errors, as_int=True),
        "vendor_name": request.form.get("inv_vendor_name", "").strip(),
        "retailer_name": request.form.get("inv_retailer_name", "").strip(),
        "customer_id": request.form.get("inv_customer_id", "").strip(),
        "store_id": request.form.get("inv_store_id", "").strip(),
    }

    if not inv["invoice_number"]:
        errors.append("Invoice Number is required")

    fields = ["product_number", "upc_number", "pack_upc", "product_description",
              "gl_code", "quantity", "unit_cost", "unit_of_measure",
              "total_adjustments", "total_discount", "extended_price", "ppc"]
    columns = {f: request.form.getlist(f + "[]") for f in fields}
    count = len(columns["product_number"])

    line_items = []
    for i in range(count):
        raw = {f: (columns[f][i].strip() if i < len(columns[f]) else "")
               for f in fields}
        # Skip completely empty rows
        if not raw["product_number"] and not raw["product_description"]:
            continue

        row_label = f"Row {len(line_items) + 1}"
        line_items.append({
            "product_number": raw["product_number"],
            "upc_number": raw["upc_number"] or None,
            "pack_upc": raw["pack_upc"] or None,
            "product_description": raw["product_description"],
            "gl_code": raw["gl_code"] or None,
            "quantity": _parse_num(raw["quantity"], f"{row_label} Quantity", errors),
            "unit_cost": _parse_num(raw["unit_cost"], f"{row_label} Unit Cost", errors),
            "unit_of_measure": raw["unit_of_measure"] or None,
            "total_adjustments": _parse_num(raw["total_adjustments"],
                                            f"{row_label} Adjustments", errors,
                                            default=0),
            "total_discount": _parse_num(raw["total_discount"],
                                         f"{row_label} Discount", errors,
                                         default=0),
            "extended_price": _parse_num(raw["extended_price"],
                                         f"{row_label} Extended Price", errors),
            "ppc": _parse_num(raw["ppc"], f"{row_label} PPC", errors),
        })

    if not line_items:
        errors.append("At least one line item is required")

    return inv, line_items, errors


@app.route("/review-pdf", methods=["POST"])
def review_pdf():
    """Receive the reviewed form data and import into PostgreSQL."""
    inv, line_items, errors = _form_to_invoice()
    raw_text = request.form.get("raw_text", "")

    if errors:
        for msg in errors:
            flash(msg, "danger")
        # Re-render the form with what the user already typed
        data = dict(inv, line_items=line_items)
        return render_template("review_pdf.html", raw_text=raw_text, data=data)

    try:
        with connection() as conn:
            with conn.cursor() as cur:
                replace_invoice(cur, inv, line_items)
            conn.commit()
    except Exception:
        log.exception("PDF invoice import failed")
        flash("Database error while importing — check the server logs", "danger")
        data = dict(inv, line_items=line_items)
        return render_template("review_pdf.html", raw_text=raw_text, data=data)

    flash(
        f"Import successful: 1 invoice and {len(line_items)} items imported/updated",
        "success",
    )
    return redirect(url_for("upload_pdf"))


if __name__ == "__main__":
    app.run(debug=True)
