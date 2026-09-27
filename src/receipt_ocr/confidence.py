"""Combines per-field OCR confidence with rule checks into the set of
review reasons for a receipt. A receipt with zero reasons is auto-accepted;
anything else -- low confidence OR a failed rule check -- goes to the
review queue. Nothing is accepted silently just because OCR ran without
raising an exception.
"""

from __future__ import annotations

from .models import FieldExtraction, LineItem

CONFIDENCE_THRESHOLD = 0.75
TOTAL_MISMATCH_TOLERANCE = 0.005  # currency rounding only; no tax is modelled


def field_reasons(field_name: str, field: FieldExtraction) -> list[str]:
    reasons = []
    if not field.ok:
        reasons.append(field.reason or f"{field_name}_invalid")
    elif field.confidence < CONFIDENCE_THRESHOLD:
        reasons.append(f"low_confidence_{field_name}:{field.confidence:.2f}")
    return reasons


def item_confidence_reasons(items: list[LineItem]) -> list[str]:
    """Per-item confidence check. The receipt-level mean item confidence is
    not checked anywhere else in classify() -- a single very-low-confidence
    item line must not be averaged away by several high-confidence ones, so
    every item is tested against the same threshold individually."""
    reasons = []
    for item in items:
        if item.confidence < CONFIDENCE_THRESHOLD:
            reasons.append(f"low_confidence_item:{item.name}:{item.confidence:.2f}")
    return reasons


def reconciliation_reasons(
    total: FieldExtraction, items: list[LineItem], unparsed_item_reasons: list[str]
) -> list[str]:
    reasons = list(unparsed_item_reasons)
    if not items:
        reasons.append("no_items_parsed")
        return reasons
    if total.ok:
        items_sum = round(sum(i.amount for i in items), 2)
        total_value = round(float(total.value), 2)
        if abs(items_sum - total_value) > TOTAL_MISMATCH_TOLERANCE:
            reasons.append(f"total_mismatch:items_sum={items_sum:.2f}:total={total_value:.2f}")
    return reasons


def classify(
    shop: FieldExtraction,
    date: FieldExtraction,
    total: FieldExtraction,
    currency: FieldExtraction,
    items: list[LineItem],
    unparsed_item_reasons: list[str],
) -> list[str]:
    reasons: list[str] = []
    reasons += field_reasons("shop", shop)
    reasons += field_reasons("date", date)
    reasons += field_reasons("total", total)
    reasons += field_reasons("currency", currency)
    reasons += item_confidence_reasons(items)
    reasons += reconciliation_reasons(total, items, unparsed_item_reasons)
    return reasons
