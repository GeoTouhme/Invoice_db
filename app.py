from flask import Flask, render_template, request, jsonify, abort
from db import query

app = Flask(__name__)


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

@app.route("/invoice/<int:invoice_number>")
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


if __name__ == "__main__":
    app.run(debug=True)
