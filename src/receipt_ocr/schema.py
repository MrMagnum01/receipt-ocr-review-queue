"""Strict parsing grammar, CSV header contracts and formula-injection-safe
CSV encoding, shared by the pipeline and the evaluator.

Grammar is declared, not inferred: an amount or date that does not match one
of the accepted patterns is rejected, never guessed at.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Money grammar: dot-decimal, optional exactly-3-digit thousands grouping.
# Matches the same declared grammar used by the excel-consolidation demo.
# Accepts:  9.99   1234.56   1,234.56   12,345,678.90
# Rejects:  1,25 (2-digit group)  1.234,56 (comma decimal)  1,2345.00
# ---------------------------------------------------------------------------
_MONEY_RE = re.compile(r"^\d{1,3}(,\d{3})*\.\d{2}$|^\d+\.\d{2}$")

# Currency indicators a receipt may print. Symbol/code -> ISO 4217.
CURRENCY_MARKERS: dict[str, str] = {
    "$": "USD",
    "USD": "USD",
    "US$": "USD",
    "€": "EUR",  # EUR sign
    "EUR": "EUR",
    "£": "GBP",  # GBP sign
    "GBP": "GBP",
}

# Fixed set of date formats the extractor will try, in order. Anything that
# does not match one of these exactly is rejected as invalid_date, not
# reinterpreted. (Matches the excel-consolidation demo's declared-grammar
# approach to dates.)
DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",  # 2026-03-14
    "%d/%m/%Y",  # 14/03/2026
    "%d-%m-%Y",  # 14-03-2026
    "%d %b %Y",  # 14 Mar 2026
)


class SchemaError(ValueError):
    """Raised when a CSV file's header does not match the declared contract."""


def parse_money(text: str) -> float | None:
    """Return the amount as a float if `text` matches the declared money
    grammar exactly; None otherwise. Never strips symbols/commas blindly."""
    text = text.strip()
    if not _MONEY_RE.match(text):
        return None
    return round(float(text.replace(",", "")), 2)


# Markers, longest first, so "US$" is tried before "$".
_ORDERED_MARKERS = tuple(sorted(CURRENCY_MARKERS, key=len, reverse=True))


def parse_money_with_symbol(text: str) -> tuple[float | None, str | None]:
    """Like parse_money, but also accepts a single unambiguous currency
    marker glued directly onto the digits (e.g. "$79.74"), which OCR
    commonly produces as one token. Returns (amount, iso_code); iso_code is
    None when no marker was attached. A token still has to reduce to
    exactly one recognised marker plus a grammar-valid amount -- anything
    else (unknown prefix, no digits after stripping) is rejected, not
    guessed at.
    """
    text = text.strip()
    amount = parse_money(text)
    if amount is not None:
        return amount, None
    for marker in _ORDERED_MARKERS:
        if text.startswith(marker) and len(text) > len(marker):
            amount = parse_money(text[len(marker):])
            if amount is not None:
                return amount, CURRENCY_MARKERS[marker]
    return None, None


# ---------------------------------------------------------------------------
# Formula-injection-safe CSV encoding.
# A field whose first character (after stripping leading whitespace) is one
# of these opens as a formula in Excel/Sheets/LibreOffice if left as-is. We
# neutralise it by prefixing a single quote, which forces text
# interpretation while keeping the human-visible value unchanged apart from
# that leading marker being disarmed.
# ---------------------------------------------------------------------------
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> str:
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + text
    return text


# ---------------------------------------------------------------------------
# CSV header contracts.
# ---------------------------------------------------------------------------
ACCEPTED_HEADER: tuple[str, ...] = (
    "receipt_id",
    "shop",
    "date",
    "total",
    "currency",
    "items_sum",
    "item_count",
    "shop_confidence",
    "date_confidence",
    "total_confidence",
    "currency_confidence",
    "mean_ocr_confidence",
    "image_path",
)

REVIEW_HEADER: tuple[str, ...] = ACCEPTED_HEADER + ("reasons",)

MANIFEST_HEADER: tuple[str, ...] = (
    "receipt_id",
    "image_path",
    "outcome",  # "accepted" or "review"
)


def validate_header(fieldnames: list[str] | None, expected: tuple[str, ...], *, source: str) -> None:
    """Raise SchemaError if a CSV's actual header doesn't match the
    declared contract exactly (order and names)."""
    actual = tuple(fieldnames or ())
    if actual != expected:
        raise SchemaError(
            f"{source}: header mismatch.\n  expected: {list(expected)}\n  actual:   {list(actual)}"
        )
