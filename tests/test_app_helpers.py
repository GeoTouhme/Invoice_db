from app import _paginate, _parse_num


def test_paginate_normal():
    page, per_page, offset = _paginate("3")
    assert (page, per_page, offset) == (3, 50, 100)


def test_paginate_bad_input_defaults_to_first_page():
    for bad in ("abc", "", None, "1.5"):
        page, _, offset = _paginate(bad)
        assert (page, offset) == (1, 0)


def test_paginate_clamps_below_one():
    page, _, offset = _paginate("-5")
    assert (page, offset) == (1, 0)


def test_parse_num_accepts_currency_formatting():
    errors = []
    assert _parse_num("$1,234.50", "Total", errors) == 1234.5
    assert errors == []


def test_parse_num_int_mode():
    errors = []
    assert _parse_num("12", "Count", errors, as_int=True) == 12
    assert errors == []


def test_parse_num_empty_returns_default():
    errors = []
    assert _parse_num("", "Total", errors) is None
    assert _parse_num(None, "Adj", errors, default=0) == 0
    assert errors == []


def test_parse_num_required_empty_records_error():
    errors = []
    _parse_num("", "Total", errors, required=True)
    assert errors == ["Total is required"]


def test_parse_num_invalid_records_error():
    errors = []
    assert _parse_num("12.5O", "Qty", errors) is None
    assert "Qty" in errors[0]
