import csv
import json

from receipt_ocr.evaluate import evaluate
from receipt_ocr.pipeline import process
from receipt_ocr.schema import ACCEPTED_HEADER, REVIEW_HEADER


def _read_csv(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_every_input_lands_in_exactly_one_output(corpus, tmp_path):
    out_dir = tmp_path / "out"
    summary = process(corpus["dir"] / "images", out_dir)

    assert summary["total_images"] == len(corpus["records"])
    assert summary["accepted"] + summary["review"] == summary["total_images"]

    accepted_ids = {r["receipt_id"] for r in _read_csv(out_dir / "accepted.csv")}
    review_ids = {r["receipt_id"] for r in _read_csv(out_dir / "review_queue.csv")}
    assert accepted_ids & review_ids == set()  # never both

    all_ids = {r.receipt_id for r in corpus["records"]}
    assert accepted_ids | review_ids == all_ids  # never neither


def test_csv_headers_match_declared_schema(corpus, tmp_path):
    out_dir = tmp_path / "out"
    process(corpus["dir"] / "images", out_dir)

    with (out_dir / "accepted.csv").open(newline="") as f:
        assert next(csv.reader(f)) == list(ACCEPTED_HEADER)
    with (out_dir / "review_queue.csv").open(newline="") as f:
        assert next(csv.reader(f)) == list(REVIEW_HEADER)


def test_manifest_accounts_for_every_receipt(corpus, tmp_path):
    out_dir = tmp_path / "out"
    process(corpus["dir"] / "images", out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text())

    receipt_ids = {r["receipt_id"] for r in manifest["receipts"]}
    assert receipt_ids == {r.receipt_id for r in corpus["records"]}
    outcomes = {r["outcome"] for r in manifest["receipts"]}
    assert outcomes <= {"accepted", "review"}
    assert manifest["summary"]["accepted"] + manifest["summary"]["review"] == manifest["summary"]["total_images"]


def test_no_leftover_temp_files_after_publish(corpus, tmp_path):
    out_dir = tmp_path / "out"
    process(corpus["dir"] / "images", out_dir)
    leftovers = [p for p in out_dir.iterdir() if p.name.endswith(".tmp") or p.name.startswith(".")]
    assert leftovers == []


def test_evaluate_runs_and_scores_are_in_range(corpus, tmp_path):
    out_dir = tmp_path / "out"
    process(corpus["dir"] / "images", out_dir)
    report = evaluate(out_dir, corpus["dir"] / "ground_truth.json")

    assert report["total_receipts"] == len(corpus["records"])
    assert 0.0 <= report["review_queue_rate"] <= 1.0
    for field, acc in report["per_field_accuracy"].items():
        assert acc is None or 0.0 <= acc <= 1.0
    if report["auto_accept_precision"] is not None:
        assert 0.0 <= report["auto_accept_precision"] <= 1.0
    assert (out_dir / "evaluation_report.json").exists()


def test_auto_accepted_receipts_are_fully_correct_on_this_corpus(corpus, tmp_path):
    # the headline claim this demo makes: whatever clears the confidence/
    # rule bar and gets auto-accepted should, on this synthetic set, be
    # completely correct. If this regresses, the threshold/rules need
    # revisiting -- it should not be silently accepted as "good enough".
    out_dir = tmp_path / "out"
    process(corpus["dir"] / "images", out_dir)
    report = evaluate(out_dir, corpus["dir"] / "ground_truth.json")
    if report["accepted_count"] > 0:
        assert report["auto_accept_precision"] == 1.0
