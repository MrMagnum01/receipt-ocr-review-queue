"""Measures pipeline output against generator ground truth. Every number
this prints is measured on the synthetic set for the given seed -- never
asserted, never presented as a real-world accuracy claim.

Validates the CSV headers it reads before trusting a single row: a header
that doesn't match the declared schema contract is a hard failure, not a
best-effort parse.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .atomic import atomic_write_text
from .schema import ACCEPTED_HEADER, REVIEW_HEADER, validate_header

FIELDS = ("shop", "date", "total", "currency", "items")


def _unescape(value: str) -> str:
    # undo our own formula-injection guard (schema.csv_safe), never real data
    if value.startswith("'") and len(value) > 1 and value[1] in ("=", "+", "-", "@", "\t", "\r"):
        return value[1:]
    return value


def _load_csv(path: Path, expected_header: tuple[str, ...]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    if not path.exists():
        return rows
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate_header(reader.fieldnames, expected_header, source=str(path))
        for raw in reader:
            row = {k: _unescape(v) for k, v in raw.items()}
            rows[row["receipt_id"]] = row
    return rows


def _load_ground_truth(path: Path) -> dict[str, dict]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {r["receipt_id"]: r for r in records}


def evaluate(out_dir: str | Path, ground_truth_path: str | Path) -> dict:
    out_dir = Path(out_dir)
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    accepted = _load_csv(out_dir / "accepted.csv", ACCEPTED_HEADER)
    review = _load_csv(out_dir / "review_queue.csv", REVIEW_HEADER)
    gt = _load_ground_truth(Path(ground_truth_path))

    receipts = manifest["receipts"]
    if set(r["receipt_id"] for r in receipts) != set(gt.keys()):
        raise ValueError("manifest and ground truth cover a different set of receipts")

    field_correct = {f: 0 for f in FIELDS}
    field_total = {f: 0 for f in FIELDS}
    accepted_total = 0
    accepted_fully_correct = 0

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
                accepted_fully_correct += 1

    n = len(receipts)
    report = {
        "seed_note": "measured on this synthetic set only; not a real-world accuracy claim",
        "total_receipts": n,
        "review_queue_rate": round(len(review) / n, 4) if n else 0.0,
        "accepted_count": accepted_total,
        "per_field_accuracy": {
            f: round(field_correct[f] / field_total[f], 4) if field_total[f] else None for f in FIELDS
        },
        "auto_accept_precision": round(accepted_fully_correct / accepted_total, 4) if accepted_total else None,
    }
    atomic_write_text(out_dir / "evaluation_report.json", json.dumps(report, indent=2, sort_keys=True))
    return report
