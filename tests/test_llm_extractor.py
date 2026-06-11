from llm_extractor import _as_num, _clean_json, _normalize


def test_clean_json_strips_markdown_fences():
    assert _clean_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _clean_json('```\n{"a": 1}\n```') == '{"a": 1}'
    assert _clean_json('{"a": 1}') == '{"a": 1}'


def test_clean_json_extracts_object_from_surrounding_text():
    assert _clean_json('Here is the data: {"a": 1} hope it helps') == '{"a": 1}'


def test_as_num_handles_currency_formatting():
    assert _as_num("$1,234.50") == 1234.5
    assert _as_num(7) == 7.0
    assert _as_num("") is None
    assert _as_num(None) is None
    assert _as_num("abc") is None


def test_normalize_rejects_non_dict():
    assert _normalize(None) is None
    assert _normalize([1, 2]) is None
    assert _normalize("text") is None


def test_normalize_rejects_useless_output():
    assert _normalize({"vendor_name": "X"}) is None


def test_normalize_fills_missing_keys_and_coerces():
    data = _normalize({
        "invoice_number": 12345,           # number instead of string
        "invoice_total": "$1,000.00",      # formatted string
        "line_items": [
            {"product_number": "P1", "quantity": "2", "unit_cost": "$5.00"},
            {"product_number": "", "product_description": ""},  # empty → dropped
            "not-a-dict",                                       # ignored
        ],
    })
    assert data["invoice_number"] == "12345"
    assert data["invoice_total"] == 1000.0
    assert data["vendor_name"] == ""        # missing key filled in
    assert len(data["line_items"]) == 1
    item = data["line_items"][0]
    assert item["quantity"] == 2.0
    assert item["unit_cost"] == 5.0
    assert item["pack_upc"] == ""           # missing key filled in
