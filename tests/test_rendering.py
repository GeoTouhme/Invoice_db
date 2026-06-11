"""Render smoke tests — pages render against a stubbed query() so no
PostgreSQL is needed."""

from datetime import date
from decimal import Decimal

import pytest

import app as app_module

PRODUCT_ROW = {
    "product_number": "P1",
    "upc_number": "034100576363",
    "product_description": "CORONA EXTRA 12PK",
    "department": "Beer",
    "quantity": Decimal("2.00"),
    "unit_of_measure": "CA",
    "unit_cost": Decimal("10.00"),
    "total_adjustments": Decimal("0.00"),
    "total_discount": Decimal("0.00"),
    "extended_price": Decimal("20.00"),
    "invoice_number": "INV-1",
    "invoice_date": date(2026, 1, 15),
    "vendor_name": "Smith & Sons",
}

INVOICE_ROW = {
    "invoice_number": "INV-1",
    "invoice_date": date(2026, 1, 15),
    "invoice_due_date": None,
    "process_date": None,
    "invoice_total": Decimal("20.00"),
    "item_count": 1,
    "vendor_name": "Smith & Sons",
    "retailer_name": "Balport",
    "customer_id": "C1",
    "store_id": "000001",
}

ITEM_ROW = {
    "product_number": "P1",
    "upc_number": "034100576363",
    "product_description": "CORONA EXTRA 12PK",
    "gl_code": "Beer",
    "quantity": Decimal("2.00"),
    "unit_cost": Decimal("10.00"),
    "unit_of_measure": "CA",
    "total_adjustments": Decimal("0.00"),
    "total_discount": Decimal("0.00"),
    "extended_price": Decimal("19.00"),  # != invoice_total → mismatch warning
}


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False
    return app_module.app.test_client()


def test_index_renders(monkeypatch, client):
    def fake_query(sql, params=(), one=False):
        if one:
            return {"n": 51, "spend": Decimal("1020.00")}
        if "DISTINCT gl_code" in sql:
            return [{"gl_code": "Beer"}]
        if "DISTINCT vendor_name" in sql:
            return [{"vendor_name": "Smith & Sons"}]
        return [PRODUCT_ROW]

    monkeypatch.setattr(app_module, "query", fake_query)
    resp = client.get("/?vendor=Smith %26 Sons&page=1")
    assert resp.status_code == 200
    assert b"CORONA EXTRA 12PK" in resp.data
    assert b"$1,020.00" in resp.data          # spend summary
    assert b"Next" in resp.data               # pagination rendered (2 pages)


def test_index_bad_page_renders(monkeypatch, client):
    def fake_query(sql, params=(), one=False):
        if one:
            return {"n": 0, "spend": 0}
        return []

    monkeypatch.setattr(app_module, "query", fake_query)
    resp = client.get("/?page=abc")
    assert resp.status_code == 200
    assert b"No results" in resp.data


def test_invoice_detail_renders_with_mismatch_warning(monkeypatch, client):
    def fake_query(sql, params=(), one=False):
        if one:
            return dict(INVOICE_ROW)
        return [dict(ITEM_ROW)]

    monkeypatch.setattr(app_module, "query", fake_query)
    resp = client.get("/invoice/INV-1")
    assert resp.status_code == 200
    assert b"Smith &amp; Sons" in resp.data
    assert b"Line items add up to" in resp.data   # 19.00 vs 20.00


def test_invoice_detail_tolerates_null_total(monkeypatch, client):
    inv = dict(INVOICE_ROW, invoice_total=None)

    def fake_query(sql, params=(), one=False):
        return dict(inv) if one else [dict(ITEM_ROW)]

    monkeypatch.setattr(app_module, "query", fake_query)
    resp = client.get("/invoice/INV-1")
    assert resp.status_code == 200


def test_static_pages_render(client):
    assert client.get("/stats").status_code == 200
    assert client.get("/upload").status_code == 200
    assert client.get("/upload-pdf").status_code == 200


def test_review_pdf_validation_rerenders_form(client):
    resp = client.post("/review-pdf", data={
        "inv_invoice_number": "",            # missing → validation error
        "product_number[]": ["P1"],
        "upc_number[]": [""], "pack_upc[]": [""],
        "product_description[]": ["Test"], "gl_code[]": ["Beer"],
        "quantity[]": ["2"], "unit_cost[]": ["bad-number"],
        "unit_of_measure[]": ["EA"], "total_adjustments[]": ["0"],
        "total_discount[]": ["0"], "extended_price[]": ["20"],
        "ppc[]": [""],
        "raw_text": "some pdf text",
    })
    assert resp.status_code == 200
    assert b"Invoice Number is required" in resp.data
    assert b"is not a valid number" in resp.data
    # user's data is preserved in the re-rendered form
    assert b"some pdf text" in resp.data
    assert b'value="Test"' in resp.data


def test_login_required_when_password_set(monkeypatch, client):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]

    assert client.get("/login").status_code == 200

    resp = client.post("/login", data={"username": "admin", "password": "s3cret"})
    assert resp.status_code == 302
    with client.session_transaction() as sess:
        assert sess["logged_in"] is True


def test_login_rejects_wrong_password(monkeypatch, client):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "s3cret")
    resp = client.post("/login", data={"username": "admin", "password": "wrong"},
                       follow_redirects=True)
    assert b"Invalid username or password" in resp.data
    with client.session_transaction() as sess:
        assert "logged_in" not in sess
