"""Orchestrates preprocess -> OCR -> field extraction -> confidence/rule
classification -> atomic publish of accepted.csv, review_queue.csv and a
manifest.json that accounts for every input image.

No silent drops: every image file discovered under the input directory
produces exactly one row in exactly one of the two output CSVs, and every
receipt lands in exactly one of three manifest outcomes -- "accepted",
"review" (a business-rule/confidence check failed), or "error" (the image
itself couldn't be opened or OCR'd). A file that can't even be opened/OCR'd
still gets a review_queue.csv row with a categorised "processing_error"
reason, never a skip, a crash, or a silently-empty result.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytesseract
from PIL import Image, UnidentifiedImageError

from .atomic import atomic_publish_set
from .confidence import classify
from .extract import extract_date, extract_items, extract_shop, extract_total_and_currency
from .models import ExtractionResult, FieldExtraction
from .ocr import run_ocr
from .preprocess import preprocess
from .schema import ACCEPTED_HEADER, REVIEW_HEADER, csv_safe

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def discover_images(input_dir: str | Path) -> list[Path]:
    input_dir = Path(input_dir)
    return sorted(
        p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def _find_duplicate_receipt_ids(images: list[Path]) -> dict[str, list[Path]]:
    """receipt_id is the image's filename stem, so r.png and r.jpg would
    silently collide into one id. Detect that before anything is
    processed or published -- refusing an ambiguous batch outright rather
    than letting one image's row overwrite the other's."""
    by_id: dict[str, list[Path]] = {}
    for p in images:
        by_id.setdefault(p.stem, []).append(p)
    return {rid: paths for rid, paths in by_id.items() if len(paths) > 1}


def _error_result(receipt_id: str, image_path: Path, exc: BaseException) -> ExtractionResult:
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


def process_receipt(image_path: Path) -> ExtractionResult:
    receipt_id = image_path.stem

    # Phase 1: load/decode the image itself.
    try:
        img = Image.open(image_path)
        img.load()
        pre = preprocess(img)
    except (OSError, UnidentifiedImageError) as exc:
        return _error_result(receipt_id, image_path, exc)

    # Phase 2: OCR. Scoped tightly to just the engine call so a declared
    # OCR failure (a bad/unreadable image that decodes fine but the engine
    # rejects, or the subprocess hanging past run_ocr's timeout) is turned
    # into a categorised per-image error -- without also swallowing a
    # genuine programmer bug in extraction/classification below, which
    # should still crash loudly.
    try:
        ocr_result = run_ocr(pre)
    except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError, RuntimeError) as exc:
        return _error_result(receipt_id, image_path, exc)

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


def _csv_text(header: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=list(header), lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        safe_row = {k: csv_safe(v) for k, v in row.items()}
        writer.writerow(safe_row)
    return buf.getvalue()


def _write_csv(path: Path, header: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    """Single-file atomic CSV write. Used directly by callers (and tests)
    that publish one file on its own; `process()` below publishes the
    accepted/review/manifest triple together via `atomic_publish_set`."""
    from .atomic import atomic_write_text

    atomic_write_text(path, _csv_text(header, rows))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def process(input_dir: str | Path, out_dir: str | Path) -> dict:
    input_dir = Path(input_dir)
    out_dir = Path(out_dir)
    images = discover_images(input_dir)

    duplicates = _find_duplicate_receipt_ids(images)
    if duplicates:
        detail = "; ".join(
            f"{rid} <- {', '.join(p.name for p in paths)}" for rid, paths in sorted(duplicates.items())
        )
        raise ValueError(
            f"refusing to publish: {len(duplicates)} receipt id(s) claimed by more than one input file "
            f"(receipt_id is the filename stem): {detail}"
        )

    accepted_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []

    accepted_count = 0
    review_count = 0
    error_count = 0

    for image_path in images:
        result = process_receipt(image_path)
        row = _row(result)
        if result.error is not None:
            outcome = "error"
        elif result.needs_review:
            outcome = "review"
        else:
            outcome = "accepted"

        if outcome == "accepted":
            accepted_rows.append(row)
            accepted_count += 1
        else:
            review_row = dict(row)
            review_row["reasons"] = "; ".join(result.review_reasons)
            review_rows.append(review_row)
            if outcome == "error":
                error_count += 1
            else:
                review_count += 1

        manifest_rows.append({"receipt_id": result.receipt_id, "image_path": result.image_path, "outcome": outcome})

    accepted_text = _csv_text(ACCEPTED_HEADER, accepted_rows)
    review_text = _csv_text(REVIEW_HEADER, review_rows)

    summary = {
        "total_images": len(images),
        "accepted": accepted_count,
        "review": review_count,
        "error": error_count,
    }
    assert summary["accepted"] + summary["review"] + summary["error"] == summary["total_images"], (
        "reconciliation failure: every discovered image must land in exactly one outcome"
    )

    # Bind the manifest to the exact content it was generated alongside via
    # a hash of each CSV. `evaluate()` re-hashes the files it reads and
    # refuses to trust them if either has drifted from what this manifest
    # published -- the residual protection atomic_publish_set's own
    # docstring calls out for a crash landing between two of its renames.
    manifest = {
        "summary": summary,
        "receipts": manifest_rows,
        "content_sha256": {
            "accepted.csv": _sha256(accepted_text),
            "review_queue.csv": _sha256(review_text),
        },
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True)

    atomic_publish_set(
        {
            out_dir / "accepted.csv": accepted_text,
            out_dir / "review_queue.csv": review_text,
            out_dir / "manifest.json": manifest_text,
        }
    )

    return summary
