"""Regression tests for Astra's remaining MUST-FIX items (2026-09-27
rereview, items 3 and 4): evaluate() must refuse to score a run whose
ground truth has duplicate receipt ids, and must refuse to score a run
whose manifest doesn't carry a complete, well-formed, matching pair of
CSV content hashes -- never silently accept by dropping the duplicate or
skipping the check.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from receipt_ocr.evaluate import evaluate
from receipt_ocr.ocr import OcrLine, OcrResult
from receipt_ocr.pipeline import process


def _line(text, conf=99):
    return OcrLine(text=text, words=[(w, conf) for w in text.split(" ")])


_LINES = [
    _line("Corner Grocery"),
    _line("Date: 2026-03-14"),
    _line("Milk x1 10.00"),
    _line("TOTAL USD 10.00"),
]

_GT_RECORD = {
    "receipt_id": "r",
    "shop": "Corner Grocery",
    "date": "2026-03-14",
    "total": 10.0,
    "currency": "USD",
    "items": [{"name": "Milk", "qty": 1, "unit_price": 10.0}],
}


@pytest.fixture
def published_run(tmp_path):
    """One real receipt run through the pipeline (OCR mocked, everything
    else real), publishing accepted.csv/review_queue.csv/manifest.json
    with a genuine, matching content_sha256 pair."""
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    Image.new("RGB", (100, 100), "white").save(images_dir / "r.png")
    out_dir = tmp_path / "out"
    with patch("receipt_ocr.pipeline.run_ocr", return_value=OcrResult(_LINES, "", 99)):
        process(images_dir, out_dir)
    gt_path = tmp_path / "gt.json"
    gt_path.write_text(json.dumps([_GT_RECORD]))
    return out_dir, gt_path


def test_valid_run_scores_normally(published_run):
    # sanity baseline: the happy path this file's refusals are contrasted
    # against must still score, not just raise.
    out_dir, gt_path = published_run
    report = evaluate(out_dir, gt_path)
    assert report["auto_accept_scored_field_agreement"] == 1.0


def test_duplicate_ground_truth_ids_refused(published_run):
    # Astra probe: a conflicting duplicate ground-truth pair (total 900
    # then 10 for the same id "r") used to score 1.0 because
    # _load_ground_truth built its map with a dict comprehension, which
    # silently keeps only the last record for a repeated id.
    out_dir, gt_path = published_run
    conflicting = [{**_GT_RECORD, "total": 900.0}, dict(_GT_RECORD)]
    gt_path.write_text(json.dumps(conflicting))
    with pytest.raises(ValueError, match="duplicate ground-truth receipt_id"):
        evaluate(out_dir, gt_path)


def test_missing_content_hash_map_refused(published_run):
    # Astra probe: popping content_sha256 entirely used to default to {}
    # and score 1.0 because the check only iterated keys present.
    out_dir, gt_path = published_run
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.pop("content_sha256")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="content_sha256 mapping"):
        evaluate(out_dir, gt_path)


def test_null_content_hash_map_refused(published_run):
    out_dir, gt_path = published_run
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_sha256"] = None
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="content_sha256 mapping"):
        evaluate(out_dir, gt_path)


def test_partial_content_hash_refused(published_run):
    # only one of the two required named hashes present -- must be
    # refused exactly like a missing map, not scored on the one check
    # that happens to still be there.
    out_dir, gt_path = published_run
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_sha256"].pop("review_queue.csv")
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="missing or malformed"):
        evaluate(out_dir, gt_path)


def test_malformed_content_hash_refused(published_run):
    out_dir, gt_path = published_run
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_sha256"]["accepted.csv"] = "not-a-hash"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="missing or malformed"):
        evaluate(out_dir, gt_path)


def test_mismatched_content_hash_still_refused(published_run):
    # unchanged behaviour: a well-formed but wrong hash must still be
    # caught as a mismatch (not merely "malformed").
    out_dir, gt_path = published_run
    manifest_path = out_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["content_sha256"]["accepted.csv"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="does not match the file"):
        evaluate(out_dir, gt_path)
