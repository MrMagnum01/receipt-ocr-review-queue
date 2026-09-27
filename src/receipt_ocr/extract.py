"""Field extraction: turns OCR'd lines into shop / date / total / currency /
items, each with a confidence and, on failure, an explicit reason.

Grammar is strict throughout: a value that doesn't match one of the
declared patterns is rejected (ok=False, reason set), never guessed at.
Nothing here silently drops a line it can't parse -- an item line that
doesn't match the expected shape is recorded as an "unparsed_item_line"
review reason rather than being dropped from consideration.
"""

from __future__ import annotations

import difflib
import re
from datetime import datetime

from .models import FieldExtraction, LineItem
from .ocr import OcrLine, OcrResult
from .schema import CURRENCY_MARKERS, DATE_FORMATS, parse_money, parse_money_with_symbol
from .shops import SHOP_LAYOUTS

_SHOP_NAMES = [s.name for s in SHOP_LAYOUTS]
_SHOP_NAME_MATCH_MIN_RATIO = 0.72

_ITEM_LINE_RE = re.compile(r"^(?P<name>.+?)\s+[xX](?P<qty>\d{1,2})\s+(?P<amount>\S+)$")
_TOTAL_LABEL_RE = re.compile(r"\bTOTAL\b", re.IGNORECASE)
_DATE_LABEL_RE = re.compile(r"\bDate\s*:?\s*(?P<rest>.+)$", re.IGNORECASE)


def extract_shop(lines: list[OcrLine]) -> FieldExtraction:
    best_ratio = 0.0
    best_name = None
    best_line: OcrLine | None = None
    for line in lines[:4]:  # shop name is always in the header block
        candidate = line.text.strip()
        if not candidate:
            continue
        for name in _SHOP_NAMES:
            ratio = difflib.SequenceMatcher(a=candidate.lower(), b=name.lower()).ratio()
            if ratio > best_ratio:
                best_ratio, best_name, best_line = ratio, name, line

    if best_name is None or best_ratio < _SHOP_NAME_MATCH_MIN_RATIO:
        return FieldExtraction(value=None, confidence=0.0, ok=False, reason="unknown_shop")

    conf = best_ratio * ((best_line.mean_conf if best_line else 0.0) / 100.0)
    return FieldExtraction(value=best_name, confidence=round(conf, 3), ok=True)


def extract_date(lines: list[OcrLine]) -> FieldExtraction:
    for line in lines:
        m = _DATE_LABEL_RE.search(line.text)
        if not m:
            continue
        candidate = m.group("rest").strip()
        for fmt in DATE_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
            return FieldExtraction(
                value=parsed.isoformat(),
                confidence=round(line.mean_conf / 100.0, 3),
                ok=True,
            )
        # a "Date:" label was found but nothing after it matched any
        # declared format -- reject rather than guess.
        return FieldExtraction(
            value=None, confidence=round(line.mean_conf / 100.0, 3), ok=False, reason="invalid_date"
        )
    return FieldExtraction(value=None, confidence=0.0, ok=False, reason="date_not_found")


def extract_total_and_currency(lines: list[OcrLine]) -> tuple[FieldExtraction, FieldExtraction]:
    total_line = None
    for line in lines:
        if _TOTAL_LABEL_RE.search(line.text):
            total_line = line
            break

    if total_line is None:
        return (
            FieldExtraction(value=None, confidence=0.0, ok=False, reason="total_not_found"),
            FieldExtraction(value=None, confidence=0.0, ok=False, reason="total_not_found"),
        )

    # currency: every distinct ISO code implied by a marker token on the
    # line, whether standalone ("USD") or glued onto the amount ("$79.74").
    found_codes: dict[str, list[int]] = {}
    for word, conf in total_line.words:
        code = CURRENCY_MARKERS.get(word) or CURRENCY_MARKERS.get(word.upper())
        if code:
            found_codes.setdefault(code, []).append(conf)

    # total amount: the rightmost token on the TOTAL line that matches the
    # declared money grammar, allowing exactly one glued currency marker.
    amount = None
    amount_conf = 0
    glued_code = None
    for word, conf in reversed(total_line.words):
        value, code = parse_money_with_symbol(word)
        if value is not None:
            amount, amount_conf, glued_code = value, conf, code
            break

    if glued_code:
        found_codes.setdefault(glued_code, []).append(amount_conf)

    if len(found_codes) == 0:
        currency = FieldExtraction(value=None, confidence=0.0, ok=False, reason="currency_not_found")
    elif len(found_codes) > 1:
        currency = FieldExtraction(
            value=None, confidence=0.0, ok=False, reason="currency_conflict:" + "+".join(sorted(found_codes))
        )
    else:
        (code, confs), = found_codes.items()
        currency = FieldExtraction(value=code, confidence=round((sum(confs) / len(confs)) / 100.0, 3), ok=True)

    if amount is None:
        total = FieldExtraction(value=None, confidence=0.0, ok=False, reason="invalid_total_amount")
    else:
        total = FieldExtraction(value=f"{amount:.2f}", confidence=round(amount_conf / 100.0, 3), ok=True)

    return total, currency


def extract_items(lines: list[OcrLine]) -> tuple[list[LineItem], list[str], float]:
    """Returns (items, unparsed_line_reasons, mean item-line confidence)."""
    items: list[LineItem] = []
    unparsed: list[str] = []
    confs: list[float] = []

    for line in lines:
        text = line.text.strip()
        if not text or _TOTAL_LABEL_RE.search(text):
            continue
        m = _ITEM_LINE_RE.match(text)
        if not m:
            continue  # not shaped like an item line (header/footer/etc.) -- not an error
        qty = int(m.group("qty"))
        amount = parse_money(m.group("amount"))
        if amount is None or qty <= 0:
            snippet = text[:40].replace(",", ";")
            unparsed.append(f"unparsed_item_line:{snippet}")
            continue
        unit_price = round(amount / qty, 2)
        items.append(LineItem(name=m.group("name").strip(), qty=qty, unit_price=unit_price))
        confs.append(line.mean_conf)

    mean_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return items, unparsed, round(mean_conf, 3)
