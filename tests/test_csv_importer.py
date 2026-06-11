import pytest

from csv_importer import REQUIRED_HEADERS, _to_float, _to_int, parse_csv

HEADER_ROW = ",".join(f'"{h}"' for h in REQUIRED_HEADERS)


def _write_csv(tmp_path, rows):
    path = tmp_path / "test.csv"
    path.write_text(HEADER_ROW + "\n" + "\n".join(rows), encoding="utf-8")
    return str(path)


def _row(inv_num, product, total="100.50", qty="2"):
    # Column order matches REQUIRED_HEADERS
    values = {
        "Invoice Date": "2026-01-15",
        "Invoice Due Date": "2026-02-15",
        "Process Date": "",
        "Invoice Number": inv_num,
        "Invoice Total": total,
        "Item Count": "1",
        "Vendor Name": "Test Vendor",
        "Retailer Name": "Balport",
        "Customer ID": "C1",
        "Store ID": "000001",
        "Product Number": product,
        "UPC Number": "034100576363",
        "Pack UPC": "",
        "Product Description": f"Product {product}",
        "GL Code": "Beer",
        "Quantity": qty,
        "Unit Cost": "10.00",
        "Unit of Measure": "CA",
        "Total Adjustments": "",
        "Total Discount": "0",
        "Extended Price": "20.00",
        "PPC": "",
    }
    return ",".join(f'"{values[h]}"' for h in REQUIRED_HEADERS)


def test_parse_csv_groups_items_by_invoice(tmp_path):
    path = _write_csv(tmp_path, [
        _row("INV-1", "P1"),
        _row("INV-1", "P2"),
        _row("INV-2", "P3"),
    ])
    invoices, items = parse_csv(path)

    assert set(invoices) == {"INV-1", "INV-2"}
    assert len(items) == 3
    # invoice tuple starts with the invoice number, ends with store id
    assert invoices["INV-1"][0] == "INV-1"
    assert invoices["INV-1"][-1] == "000001"
    # item tuple starts with invoice number
    assert items[0][0] == "INV-1"


def test_parse_csv_skips_rows_without_invoice_number(tmp_path):
    path = _write_csv(tmp_path, [_row("", "P1"), _row("INV-1", "P2")])
    invoices, items = parse_csv(path)
    assert set(invoices) == {"INV-1"}
    assert len(items) == 1


def test_parse_csv_missing_headers_raises(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Invoice Number,Product Number\nINV-1,P1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required columns"):
        parse_csv(str(path))


def test_parse_csv_numeric_conversion(tmp_path):
    path = _write_csv(tmp_path, [_row("INV-1", "P1", total="123.45", qty="3.5")])
    invoices, items = parse_csv(path)
    assert invoices["INV-1"][4] == 123.45   # Invoice Total
    assert items[0][6] == 3.5               # Quantity
    assert items[0][9] is None              # empty Total Adjustments


def test_to_float_and_to_int():
    assert _to_float("1.5") == 1.5
    assert _to_float("") is None
    assert _to_float("  ") is None
    assert _to_float(None) is None
    assert _to_int("7") == 7
    assert _to_int("") is None
