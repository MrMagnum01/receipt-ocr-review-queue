#!/usr/bin/env bash
# One-command demo run: generate synthetic degraded receipt scans, OCR +
# extract them, then measure accuracy against the recorded ground truth.
# Assumes the venv is already created and activated (see README "Setup"),
# or falls back to the system python3 if not.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

SEED="${1:-7}"
COUNT="${2:-60}"
GT_DIR="data/ground_truth"
OUT_DIR="data/output"

python3 -m receipt_ocr generate --out "$GT_DIR" --seed "$SEED" --count "$COUNT"
python3 -m receipt_ocr run --input "$GT_DIR/images" --out "$OUT_DIR"
python3 -m receipt_ocr evaluate --out "$OUT_DIR" --ground-truth "$GT_DIR/ground_truth.json"

echo
echo "Done. accepted.csv / review_queue.csv / evaluation_report.json written to $OUT_DIR/."
