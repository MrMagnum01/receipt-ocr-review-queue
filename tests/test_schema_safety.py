import pytest

from receipt_ocr.schema import (
    ACCEPTED_HEADER,
    SchemaError,
    csv_safe,
    parse_money,
    parse_money_with_symbol,
    validate_header,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("9.99", 9.99),
        ("1234.56", 1234.56),
        ("1,234.56", 1234.56),
        ("12,345,678.90", 12345678.90),
    ],
)
def test_parse_money_accepts_declared_grammar(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "1,25",  # comma-decimal, not thousands grouping
        "1.234,56",  # European grouping
        "1,2345.00",  # not a 3-digit group
        "$10.00",  # symbol not stripped by parse_money itself
        "abc",
        "",
        "10",  # no decimal part
    ],
)
def test_parse_money_rejects_everything_else(text):
    assert parse_money(text) is None


@pytest.mark.parametrize(
    "text,amount,code",
    [
        ("$79.74", 79.74, "USD"),
        ("EUR14.70", 14.70, "EUR"),
        ("79.74", 79.74, None),
    ],
)
def test_parse_money_with_symbol_strips_one_unambiguous_marker(text, amount, code):
    got_amount, got_code = parse_money_with_symbol(text)
    assert got_amount == amount
    assert got_code == code


def test_parse_money_with_symbol_rejects_conflicting_or_malformed():
    # two different currency symbols glued together: reject, don't guess.
    assert parse_money_with_symbol("$€10.00") == (None, None)
    # malformed grouping even with a marker attached: still rejected.
    assert parse_money_with_symbol("$1,25") == (None, None)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+1234", "'+1234"),
        ("-1234", "'-1234"),
        ("@cmd", "'@cmd"),
        ("Corner Grocery", "Corner Grocery"),
        ("", ""),
        (None, ""),
        (12.5, "12.5"),
    ],
)
def test_csv_safe_neutralises_formula_triggers(value, expected):
    assert csv_safe(value) == expected


def test_validate_header_accepts_exact_match():
    validate_header(list(ACCEPTED_HEADER), ACCEPTED_HEADER, source="test")


def test_validate_header_rejects_mismatch():
    with pytest.raises(SchemaError):
        validate_header(["receipt_id", "shop"], ACCEPTED_HEADER, source="test")


def test_validate_header_rejects_reordered_columns():
    reordered = tuple(reversed(ACCEPTED_HEADER))
    with pytest.raises(SchemaError):
        validate_header(list(reordered), ACCEPTED_HEADER, source="test")
