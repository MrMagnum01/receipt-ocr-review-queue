"""Orchestrates preprocess -> OCR -> field extraction -> confidence/rule
classification -> atomic publish of accepted.csv, review_queue.csv and a
manifest.json that accounts for every input image.

No silent drops: every image file discovered under the input directory
produces exactly one row in exactly one of the two output CSVs. A file
that can't even be opened/OCR'd still gets a review_queue.csv row with a
"processing_error" reason, not a skip.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .atomic import atomic_write_text
from .confidence import classify
from .extract import extract_date, extract_items, extract_shop, extract_total_and_currency
from .models import ExtractionResult
from .ocr import run_ocr
from .preprocess import preprocess
from .schema import ACCEPTED_HEADER, REVIEW_HEADER, csv_safe

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def discover_images(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    return sorted(
        p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def process_receipt(image_path: Path) -> ExtractionResult:
    receipt_id = image_path.stem
    try:
        img = Image.open(image_path)
        img.load()
        pre = preprocess(img)
        ocr_result = run_ocr(pre)

        shop = extract_shop(ocr_result.lines)
        date = extract_date(ocr_result.lines)
        total, currency = extract_total_and_currency(ocr_result.lines)
        items, unparsed_reasons, _items_conf = extract_items(ocr_result.lines)
        reasons = classify(shop, date, total, currency, items, unparsed_reasons)
        items_sum = round(sum(i.amount for i in items), 2) if items else None

        return ExtractionResult(
            receipt_id=receipt_id,
            image_path=str(image_path),
            shop=shop,
            date=date,
            total=total,
            currency=currency,
            items=items,
            items_sum=items_sum,
            ocr_mean_word_conf=round(ocr_result.mean_word_conf / 100.0, 3),
            review_reasons=reasons,
        )
    except (OSError, UnidentifiedImageError) as exc:
        from .models import FieldExtraction

        blank = FieldExtraction(value=None, confidence=0.0, ok=False, reason="processing_error")
        return ExtractionResult(
            receipt_id=receipt_id,
            image_path=str(image_path),
            shop=blank,
            date=blank,
            total=blank,
            currency=blank,
            items=[],
            items_sum=None,
            ocr_mean_word_conf=0.0,
            review_reasons=[f"processing_error:{type(exc).__name__}"],
            error=str(exc),
        )


def _row(result: ExtractionResult) -> dict[str, str]:
    return {
        "receipt_id": result.receipt_id,
        "shop": result.shop.value or "",
        "date": result.date.value or "",
        "total": result.total.value or "",
        "currency": result.currency.value or "",
        "items_sum": f"{result.items_sum:.2f}" if result.items_sum is not None else "",
        "item_count": str(len(result.items)),
        "shop_confidence": f"{result.shop.confidence:.3f}",
        "date_confidence": f"{result.date.confidence:.3f}",
        "total_confidence": f"{result.total.confidence:.3f}",
        "currency_confidence": f"{result.currency.confidence:.3f}",
        "mean_ocr_confidence": f"{result.ocr_mean_word_conf:.3f}",
        "image_path": result.image_path,
    }


def _write_csv(path: Path, header: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(header), lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        safe_row = {k: csv_safe(v) for k, v in row.items()}
        writer.writerow(safe_row)
    atomic_write_text(path, buf.getvalue())


def process(input_dir: str | Path, out_dir: str | Path) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    images = discover_images(input_dir)

    accepted_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []

    for image_path in images:
        result = process_receipt(image_path)
        row = _row(result)
        if result.needs_review:
            review_row = dict(row)
            review_row["reasons"] = "; ".join(result.review_reasons)
            review_rows.append(review_row)
            outcome = "review"
        else:
            accepted_rows.append(row)
            outcome = "accepted"
        manifest_rows.append({"receipt_id": result.receipt_id, "image_path": result.image_path, "outcome": outcome})

    _write_csv(out_dir / "accepted.csv", ACCEPTED_HEADER, accepted_rows)
    _write_csv(out_dir / "review_queue.csv", REVIEW_HEADER, review_rows)

    summary = {
        "total_images": len(images),
        "accepted": len(accepted_rows),
        "review": len(review_rows),
    }
    manifest = {"summary": summary, "receipts": manifest_rows}
    atomic_write_text(out_dir / "manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    assert summary["accepted"] + summary["review"] == summary["total_images"], (
        "reconciliation failure: every discovered image must land in exactly one output"
    )
    return summary
