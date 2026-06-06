import os

from flask import Flask, render_template, request, jsonify, abort, redirect, url_for, flash
from db import query
from csv_importer import import_csv
from pdf_extractor import extract_text_from_pdf
from llm_extractor import extract_invoice_data

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _paginate(page, per_page=50):
    page = max(1, int(page))
    return page, per_page, (page - 1) * per_page


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

        temp_path = "/tmp/balport_upload.csv"
        uploaded.save(temp_path)

        try:
            result = import_csv(temp_path, os.environ["DATABASE_URL"], truncate=False)
            flash(
                f"Import successful: {result['invoices']} invoices and {result['items']} items",
                "success",
            )
        except ValueError as exc:
            flash(f"File error: {exc}", "danger")
        except Exception as exc:
            flash(f"Unexpected error: {exc}", "danger")

        return redirect(url_for("upload"))

    return render_template("upload.html")


# ── PDF Upload ────────────────────────────────────────────────────────────────

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

        temp_path = "/tmp/balport_upload.pdf"
        uploaded.save(temp_path)

        try:
            raw_text = extract_text_from_pdf(temp_path)
        except Exception as exc:
            flash(f"Failed to extract text from PDF: {exc}", "danger")
            return redirect(url_for("upload_pdf"))

        # Optional AI auto-fill
        ai_data = extract_invoice_data(raw_text)

        # If AI failed or no key, provide empty template
        data = ai_data if ai_data else {
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

        return render_template("review_pdf.html", raw_text=raw_text, data=data)

    return render_template("upload_pdf.html")


@app.route("/review-pdf", methods=["POST"])
def review_pdf():
    """Receive the reviewed form data and import into PostgreSQL."""
    inv = {
        "invoice_number": request.form.get("inv_invoice_number", "").strip(),
        "invoice_date": request.form.get("inv_invoice_date", "").strip() or None,
        "invoice_due_date": request.form.get("inv_invoice_due_date", "").strip() or None,
        "process_date": request.form.get("inv_process_date", "").strip() or None,
        "invoice_total": request.form.get("inv_invoice_total", "").strip(),
        "item_count": request.form.get("inv_item_count", "").strip(),
        "vendor_name": request.form.get("inv_vendor_name", "").strip(),
        "retailer_name": request.form.get("inv_retailer_name", "").strip(),
        "customer_id": request.form.get("inv_customer_id", "").strip(),
        "store_id": request.form.get("inv_store_id", "").strip(),
    }

    # Gather line items from form arrays
    line_items = []
    count = len(request.form.getlist("product_number[]"))
    for i in range(count):
        line = {
            "product_number": request.form.getlist("product_number[]")[i].strip(),
            "upc_number": request.form.getlist("upc_number[]")[i].strip() or None,
            "pack_upc": request.form.getlist("pack_upc[]")[i].strip() or None,
            "product_description": request.form.getlist("product_description[]")[i].strip(),
            "gl_code": request.form.getlist("gl_code[]")[i].strip() or None,
            "quantity": request.form.getlist("quantity[]")[i].strip(),
            "unit_cost": request.form.getlist("unit_cost[]")[i].strip(),
            "unit_of_measure": request.form.getlist("unit_of_measure[]")[i].strip() or None,
            "total_adjustments": request.form.getlist("total_adjustments[]")[i].strip() or "0",
            "total_discount": request.form.getlist("total_discount[]")[i].strip() or "0",
            "extended_price": request.form.getlist("extended_price[]")[i].strip(),
            "ppc": request.form.getlist("ppc[]")[i].strip() or None,
        }
        # Skip completely empty rows
        if line["product_number"] or line["product_description"]:
            line_items.append(line)

    if not inv["invoice_number"]:
        flash("Invoice Number is required", "danger")
        return redirect(url_for("upload_pdf"))

    if not line_items:
        flash("At least one line item is required", "danger")
        return redirect(url_for("upload_pdf"))

    try:
        conn = query.__wrapped__.__globals__["get_conn"]() if hasattr(query, "__wrapped__") else None
    except Exception:
        pass

    # Build minimal CSV in memory and reuse importer
    import csv
    import io
    import tempfile
    from db import get_conn

    # We need to insert directly because csv_importer expects a file path
    conn = get_conn()
    cur = conn.cursor()

    # Upsert invoice
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
            inv["invoice_number"],
            inv["invoice_date"],
            inv["invoice_due_date"],
            inv["process_date"],
            float(inv["invoice_total"]) if inv["invoice_total"] else None,
            int(inv["item_count"]) if inv["item_count"] else None,
            inv["vendor_name"],
            inv["retailer_name"],
            inv["customer_id"],
            inv["store_id"],
        ),
    )

    # Delete old items for this invoice to keep idempotency
    cur.execute("DELETE FROM invoice_items WHERE invoice_number = %s", (inv["invoice_number"],))

    # Insert new items
    for line in line_items:
        cur.execute(
            """
            INSERT INTO invoice_items
                (invoice_number, product_number, upc_number, pack_upc, product_description,
                 gl_code, quantity, unit_cost, unit_of_measure, total_adjustments,
                 total_discount, extended_price, ppc)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                inv["invoice_number"],
                line["product_number"],
                line["upc_number"],
                line["pack_upc"],
                line["product_description"],
                line["gl_code"],
                float(line["quantity"]) if line["quantity"] else None,
                float(line["unit_cost"]) if line["unit_cost"] else None,
                line["unit_of_measure"],
                float(line["total_adjustments"]) if line["total_adjustments"] else 0,
                float(line["total_discount"]) if line["total_discount"] else 0,
                float(line["extended_price"]) if line["extended_price"] else None,
                float(line["ppc"]) if line["ppc"] else None,
            ),
        )

    conn.commit()
    cur.close()
    conn.close()

    flash(
        f"Import successful: 1 invoice and {len(line_items)} items imported/updated",
        "success",
    )
    return redirect(url_for("upload_pdf"))


if __name__ == "__main__":
    app.run(debug=True)
