import csv

from receipt_ocr.pipeline import _row, _write_csv, process
from receipt_ocr.schema import ACCEPTED_HEADER


def test_corrupt_image_goes_to_review_not_dropped(corpus, tmp_path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    # copy one good image plus one deliberately corrupt file
    good = next((corpus["dir"] / "images").glob("*.png"))
    (input_dir / good.name).write_bytes(good.read_bytes())
    (input_dir / "broken.png").write_bytes(b"not a real png")

    out_dir = tmp_path / "out"
    summary = process(input_dir, out_dir)

    assert summary["total_images"] == 2
    assert summary["accepted"] + summary["review"] == 2

    with (out_dir / "review_queue.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    broken_rows = [r for r in rows if r["receipt_id"] == "broken"]
    assert len(broken_rows) == 1
    assert "processing_error" in broken_rows[0]["reasons"]


def test_empty_input_directory_produces_headers_only_no_crash(tmp_path):
    input_dir = tmp_path / "images"
    input_dir.mkdir()
    out_dir = tmp_path / "out"

    summary = process(input_dir, out_dir)
    assert summary == {"total_images": 0, "accepted": 0, "review": 0}

    with (out_dir / "accepted.csv").open(newline="") as f:
        assert list(csv.reader(f)) == [list(ACCEPTED_HEADER)]


def test_csv_writer_neutralises_formula_injection_in_extracted_text(tmp_path):
    # even if OCR/extraction ever produced a shop name that looks like a
    # formula, the CSV writer must neutralise it before it reaches disk.
    from receipt_ocr.models import ExtractionResult, FieldExtraction

    adversarial_shop = FieldExtraction(value="=cmd|'/C calc'!A1", confidence=0.9, ok=True)
    benign = FieldExtraction(value="2025-01-01", confidence=0.9, ok=True)
    result = ExtractionResult(
        receipt_id="r0001",
        image_path="x.png",
        shop=adversarial_shop,
        date=benign,
        total=FieldExtraction(value="10.00", confidence=0.9, ok=True),
        currency=FieldExtraction(value="USD", confidence=0.9, ok=True),
        items=[],
        items_sum=None,
    )
    row = _row(result)
    assert row["shop"].startswith("=")  # in-memory value is untouched

    out_path = tmp_path / "accepted.csv"
    _write_csv(out_path, ACCEPTED_HEADER, [row])
    with out_path.open(newline="") as f:
        written = list(csv.DictReader(f))[0]
    # on-disk cell is neutralised: a leading quote forces text
    # interpretation in Excel/Sheets/LibreOffice instead of a formula.
    assert written["shop"] == "'=cmd|'/C calc'!A1"
