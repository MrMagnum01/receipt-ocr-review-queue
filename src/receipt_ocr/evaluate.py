"""Measures pipeline output against generator ground truth. Every number
this prints is measured on the synthetic set for the given seed -- never
asserted, never presented as a real-world accuracy claim.

Validates the CSV headers it reads before trusting a single row: a header
that doesn't match the declared schema contract is a hard failure, not a
best-effort parse. It also re-validates the *shape* of a completed run
before scoring it at all: duplicate receipt ids, an id in both CSVs, an id
missing from both, an unrecognised manifest outcome, summary counts that
don't reconcile, or accepted/review CSV content that no longer matches the
sha256 the manifest recorded for it (see pipeline.py's atomic_publish_set)
are all hard failures -- never silently averaged into an accuracy number.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

from .atomic import atomic_write_text
from .schema import ACCEPTED_HEADER, REVIEW_HEADER, validate_header

FIELDS = ("shop", "date", "total", "currency", "items")
PERMITTED_OUTCOMES = {"accepted", "review", "error"}
REQUIRED_HASH_NAMES = ("accepted.csv", "review_queue.csv")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _unescape(value: str) -> str:
    # undo our own formula-injection guard (schema.csv_safe), never real data
    if value.startswith("'") and len(value) > 1 and value[1] in ("=", "+", "-", "@", "\t", "\r"):
        return value[1:]
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_csv(path: Path, expected_header: tuple[str, ...]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header(reader.fieldnames, expected_header, source=str(path))
        for raw in reader:
            row = {k: _unescape(v) for k, v in raw.items()}
            rid = row["receipt_id"]
            if rid in rows:
                raise ValueError(f"{path}: duplicate receipt_id {rid!r} -- refusing to score an ambiguous file")
            rows[rid] = row
    return rows


def _load_ground_truth(path: Path) -> dict[str, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    gt: dict[str, dict] = {}
    for r in records:
        rid = r["receipt_id"]
        if rid in gt:
            raise ValueError(
                f"{path}: duplicate ground-truth receipt_id {rid!r} -- refusing to score against "
                "an ambiguous ground truth (a dict comprehension would silently keep only the last one)"
            )
        gt[rid] = r
    return gt


def _validate_content_hashes(manifest: dict, accepted_path: Path, review_path: Path) -> None:
    # Bind to the publish: a manifest whose recorded hash of either CSV no
    # longer matches what's on disk means this is not the coherent output
    # of one run (e.g. a crash landed between atomic_publish_set's
    # renames, or a file was hand-edited/replaced afterwards). Both named
    # hashes are mandatory -- a missing map, a missing/null entry, or a
    # malformed (non-hex, wrong-length) value is refused exactly like a
    # mismatch, never silently treated as "nothing to check".
    recorded_hashes = manifest.get("content_sha256")
    if not isinstance(recorded_hashes, dict):
        raise ValueError(
            "manifest.json is missing a content_sha256 mapping -- refusing to score an output "
            "that cannot be bound to a specific publish"
        )
    malformed = [
        name
        for name in REQUIRED_HASH_NAMES
        if not isinstance(recorded_hashes.get(name), str) or not _SHA256_HEX.match(recorded_hashes[name])
    ]
    if malformed:
        raise ValueError(
            f"manifest.json content_sha256 is missing or malformed for: {malformed} -- "
            "both accepted.csv and review_queue.csv hashes are required to score this output"
        )
    actual_hashes = {"accepted.csv": _sha256_file(accepted_path), "review_queue.csv": _sha256_file(review_path)}
    mismatched = [name for name in REQUIRED_HASH_NAMES if actual_hashes[name] != recorded_hashes[name]]
    if mismatched:
        raise ValueError(
            f"manifest.json content_sha256 does not match the file(s) on disk: {mismatched} -- "
            "this output directory is not the coherent result of one publish"
        )


def evaluate(out_dir: str | Path, ground_truth_path: str | Path) -> dict:
    out_dir = Path(out_dir)
    manifest_path = out_dir / "manifest.json"
    accepted_path = out_dir / "accepted.csv"
    review_path = out_dir / "review_queue.csv"
    for p in (manifest_path, accepted_path, review_path):
        if not p.exists():
            raise ValueError(f"cannot evaluate: required output file is missing: {p}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    accepted = _load_csv(accepted_path, ACCEPTED_HEADER)
    review = _load_csv(review_path, REVIEW_HEADER)
    gt = _load_ground_truth(Path(ground_truth_path))

    _validate_content_hashes(manifest, accepted_path, review_path)

    receipts = manifest["receipts"]
    manifest_ids = [r["receipt_id"] for r in receipts]
    if len(manifest_ids) != len(set(manifest_ids)):
        dupes = sorted({rid for rid in manifest_ids if manifest_ids.count(rid) > 1})
        raise ValueError(f"manifest.json has duplicate receipt_id(s): {dupes}")
    manifest_id_set = set(manifest_ids)

    if manifest_id_set != set(gt.keys()):
        raise ValueError("manifest and ground truth cover a different set of receipts")

    bad_outcomes = {r["outcome"] for r in receipts} - PERMITTED_OUTCOMES
    if bad_outcomes:
        raise ValueError(f"manifest.json has unrecognised outcome(s): {sorted(bad_outcomes)}")

    accepted_ids = set(accepted.keys())
    review_ids = set(review.keys())
    if accepted_ids & review_ids:
        raise ValueError(
            f"receipt id(s) present in both accepted.csv and review_queue.csv: {sorted(accepted_ids & review_ids)}"
        )

    expected_accepted_ids = {r["receipt_id"] for r in receipts if r["outcome"] == "accepted"}
    expected_review_ids = {r["receipt_id"] for r in receipts if r["outcome"] in ("review", "error")}
    if accepted_ids != expected_accepted_ids:
        raise ValueError("accepted.csv rows do not exactly match the manifest's 'accepted' outcomes")
    if review_ids != expected_review_ids:
        raise ValueError("review_queue.csv rows do not exactly match the manifest's 'review'/'error' outcomes")

    summary = manifest["summary"]
    if summary["accepted"] + summary["review"] + summary.get("error", 0) != summary["total_images"]:
        raise ValueError("manifest summary counts do not reconcile to total_images")
    if summary["accepted"] != len(expected_accepted_ids):
        raise ValueError("manifest summary 'accepted' count does not match the manifest's own receipt rows")
    if summary["review"] + summary.get("error", 0) != len(expected_review_ids):
        raise ValueError("manifest summary 'review'+'error' count does not match the manifest's own receipt rows")

    field_correct = {f: 0 for f in FIELDS}
    field_total = {f: 0 for f in FIELDS}
    accepted_total = 0
    accepted_fields_agree = 0

    for entry in receipts:
        rid = entry["receipt_id"]
        truth = gt[rid]
        row = accepted.get(rid) if entry["outcome"] == "accepted" else review.get(rid)
        if row is None:
            raise ValueError(f"{rid}: outcome={entry['outcome']!r} but missing from that CSV")

        checks = {}
        checks["shop"] = row["shop"] == truth["shop"]
        checks["date"] = row["date"] == truth["date"]
        try:
            checks["total"] = row["total"] != "" and abs(float(row["total"]) - truth["total"]) <= 0.005
        except ValueError:
            checks["total"] = False
        checks["currency"] = row["currency"] == truth["currency"]
        try:
            items_sum_ok = row["items_sum"] != "" and abs(float(row["items_sum"]) - truth["total"]) <= 0.005
            count_ok = row["item_count"] != "" and int(row["item_count"]) == len(truth["items"])
            checks["items"] = items_sum_ok and count_ok
        except ValueError:
            checks["items"] = False

        for f in FIELDS:
            field_total[f] += 1
            if checks[f]:
                field_correct[f] += 1

        if entry["outcome"] == "accepted":
            accepted_total += 1
            if all(checks.values()):
                accepted_fields_agree += 1

    n = len(receipts)
    report = {
        "seed_note": "measured on this synthetic set only; not a real-world accuracy claim",
        "total_receipts": n,
        "review_queue_rate": round(len(review) / n, 4) if n else 0.0,
        "accepted_count": accepted_total,
        "per_field_accuracy": {
            f: round(field_correct[f] / field_total[f], 4) if field_total[f] else None for f in FIELDS
        },
        # Of the auto-accepted receipts, the fraction that agree with ground
        # truth on every field this evaluator actually checks: shop, date,
        # total, currency, and items (sum-of-line-items + item count only --
        # NOT item names, quantities or unit prices, which this evaluator
        # does not compare). This is agreement on the scored fields, not a
        # claim that the receipt was reproduced completely correctly.
        "auto_accept_scored_field_agreement": (
            round(accepted_fields_agree / accepted_total, 4) if accepted_total else None
        ),
    }
    atomic_write_text(out_dir / "evaluation_report.json", json.dumps(report, indent=2, sort_keys=True))
    return report
