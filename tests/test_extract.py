from receipt_ocr.confidence import classify
from receipt_ocr.extract import extract_date, extract_items, extract_shop, extract_total_and_currency
from receipt_ocr.ocr import OcrLine


def line(text, conf=95):
    words = text.split(" ")
    return OcrLine(text=text, words=[(w, conf) for w in words])


def test_extract_shop_exact_match():
    result = extract_shop([line("Corner Grocery"), line("14 Maple Street")])
    assert result.ok
    assert result.value == "Corner Grocery"


def test_extract_shop_unknown_is_rejected():
    result = extract_shop([line("Totally Unknown Store"), line("1 Nowhere Ave")])
    assert not result.ok
    assert result.reason == "unknown_shop"


def test_extract_date_valid_iso():
    result = extract_date([line("Date: 2025-05-18")])
    assert result.ok
    assert result.value == "2025-05-18"


def test_extract_date_valid_dmy_text_month():
    result = extract_date([line("Date: 17 Aug 2025")])
    assert result.ok
    assert result.value == "2025-08-17"


def test_extract_date_out_of_grammar_is_rejected_not_guessed():
    result = extract_date([line("Date: 2025/05/18")])  # slashes with ISO order: not declared
    assert not result.ok
    assert result.reason == "invalid_date"


def test_extract_date_missing_label():
    result = extract_date([line("Corner Grocery")])
    assert not result.ok
    assert result.reason == "date_not_found"


def test_extract_total_plain():
    total, currency = extract_total_and_currency([line("TOTAL USD $ 43.38")])
    assert total.ok and total.value == "43.38"
    assert currency.ok and currency.value == "USD"


def test_extract_total_glued_symbol():
    total, currency = extract_total_and_currency([line("TOTAL USD $79.74")])
    assert total.ok and total.value == "79.74"
    assert currency.ok and currency.value == "USD"


def test_extract_total_conflicting_currency_symbols_rejected():
    total, currency = extract_total_and_currency([line("TOTAL $ 10.00 EUR")])
    assert not currency.ok
    assert currency.reason.startswith("currency_conflict")


def test_extract_total_not_found():
    total, currency = extract_total_and_currency([line("Thank you for shopping")])
    assert not total.ok and total.reason == "total_not_found"
    assert not currency.ok and currency.reason == "total_not_found"


def test_extract_total_ambiguous_glued_currencies_rejected_not_picked():
    # two glued currency markers with the same numeric amount: the old
    # rightmost-token search picked the last one (EUR) and never noticed
    # the $10.00 candidate to its left. Both currency and total must
    # reject this as ambiguous rather than silently resolving it.
    total, currency = extract_total_and_currency([line("TOTAL $10.00 EUR10.00")])
    assert not total.ok
    assert total.reason.startswith("ambiguous_total")
    assert not currency.ok
    assert currency.reason.startswith("currency_conflict")


def test_extract_total_conflicting_amounts_same_currency_rejected():
    # two candidate totals with no currency conflict at all -- the
    # rightmost-token search would silently pick 12.00 and drop 10.00.
    total, currency = extract_total_and_currency([line("TOTAL $10.00 $12.00")])
    assert not total.ok
    assert total.reason.startswith("ambiguous_total")


def test_classify_flags_low_confidence_item_even_with_high_receipt_mean():
    from receipt_ocr.models import FieldExtraction, LineItem

    total = FieldExtraction(value="10.00", confidence=0.95, ok=True)
    shop = FieldExtraction(value="Corner Grocery", confidence=0.95, ok=True)
    date = FieldExtraction(value="2025-01-01", confidence=0.95, ok=True)
    currency = FieldExtraction(value="USD", confidence=0.95, ok=True)
    # one item at 1% confidence, everything else confident, total matches --
    # the old code ignored item confidence entirely and auto-accepted this.
    items = [
        LineItem(name="Suspect Item", qty=1, unit_price=10.00, confidence=0.01),
    ]
    reasons = classify(shop, date, total, currency, items, [])
    assert any(r.startswith("low_confidence_item:") for r in reasons)


def test_extract_items_parses_name_qty_amount():
    items, unparsed, _conf = extract_items([line("Oat Milk 1L x2 4.98"), line("TOTAL USD $ 4.98")])
    assert len(items) == 1
    assert items[0].name == "Oat Milk 1L"
    assert items[0].qty == 2
    assert items[0].unit_price == 2.49


def test_extract_items_malformed_line_is_flagged_not_dropped_silently():
    # amount uses comma-decimal grammar (invalid) -- the line must surface
    # as an explicit unparsed reason, not vanish from consideration.
    items, unparsed, _conf = extract_items([line("Weird Item x1 4,99")])
    assert items == []
    assert len(unparsed) == 1
    assert unparsed[0].startswith("unparsed_item_line:")


def test_extract_items_ignores_non_item_lines():
    items, unparsed, _conf = extract_items([line("Corner Grocery"), line("Thank you for shopping")])
    assert items == []
    assert unparsed == []


def test_classify_flags_total_mismatch():
    from receipt_ocr.models import FieldExtraction, LineItem

    total = FieldExtraction(value="10.00", confidence=0.95, ok=True)
    shop = FieldExtraction(value="Corner Grocery", confidence=0.95, ok=True)
    date = FieldExtraction(value="2025-01-01", confidence=0.95, ok=True)
    currency = FieldExtraction(value="USD", confidence=0.95, ok=True)
    items = [LineItem(name="X", qty=1, unit_price=5.00)]  # sums to 5.00, not 10.00
    reasons = classify(shop, date, total, currency, items, [])
    assert any(r.startswith("total_mismatch") for r in reasons)


def test_classify_clean_receipt_has_no_reasons():
    from receipt_ocr.models import FieldExtraction, LineItem

    total = FieldExtraction(value="10.00", confidence=0.95, ok=True)
    shop = FieldExtraction(value="Corner Grocery", confidence=0.95, ok=True)
    date = FieldExtraction(value="2025-01-01", confidence=0.95, ok=True)
    currency = FieldExtraction(value="USD", confidence=0.95, ok=True)
    items = [LineItem(name="X", qty=2, unit_price=5.00)]  # sums to 10.00
    reasons = classify(shop, date, total, currency, items, [])
    assert reasons == []
