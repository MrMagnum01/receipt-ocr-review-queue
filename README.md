# receipt-ocr-review-queue

Turns a folder of scanned/photographed receipts into a clean `accepted.csv`
plus a `review_queue.csv` for a human to check: OCR (Tesseract) extracts
shop, date, total, currency and line items, each field gets a confidence
score from Tesseract's own word confidences, and a receipt is only
auto-accepted if every field is confident **and** its line items sum to
its printed total. Nothing is silently accepted — a receipt that fails
any check lands in the review queue with the specific reason(s) it failed,
and every input image ends up in exactly one of the two output files.

**Everything in this repo is synthetic.** The included generator renders
receipt images for 4 fictional shops with a fixed random seed and
realistic scan degradation (rotation, blur, noise, low contrast, a
crumpled/partial variant), so the whole pipeline can be demoed, tested and
measured without any real client data. No code, data, or receipt layout
here is copied from any client or employer project.

**Job type this proves:** "OCR receipts to Excel/CSV", "invoice/receipt
data extraction", "document processing with human review" — the class of
Upwork job where a client has a folder of scanned receipts and wants a
spreadsheet, but also wants confidence that whatever wasn't read cleanly
gets flagged rather than silently wrong.

## What it does

1. `generate` — renders a deterministic corpus of synthetic receipt PNGs
   from 4 fictional shop layouts (`Corner Grocery`, `Riverside Cafe`,
   `BrightMart Superstore`, `Luna Bookshop`; different fonts, alignment,
   date formats and currencies per shop) and records the exact ground
   truth (`shop`, `date`, line items, `total`, `currency`) to
   `ground_truth.json`. Each receipt gets one of six variants in rotation:
   `clean`, `rotated` (±5°), `blurred` (Gaussian blur), `noisy` (blended
   Gaussian noise), `low_contrast`, and `crumpled` (a small perspective
   warp plus noise plus a randomly cropped bottom edge, simulating a
   partially-visible scan).
2. `run` — for every image in a directory: deterministic preprocessing
   (grayscale, autocontrast, upscale, sharpen), Tesseract OCR (bounded by
   a 30s per-image timeout) with per-word confidences, then field
   extraction against a **declared grammar** (see "How extraction
   works"). Writes `accepted.csv` and `review_queue.csv`, plus a
   `manifest.json` that lists every input image and which outcome it got.
   Each of the three files is written atomically on its own (temp file,
   then rename), and all three are additionally *prepared* (written and
   fsynced to temp names) before any of them is renamed into place, so a
   write failure partway through never leaves one new file next to two
   old ones. That narrows, but doesn't eliminate, the exposure: a crash
   during the handful of renames itself is still possible in principle,
   which is why the manifest also records a sha256 of each CSV's content
   — `evaluate` refuses to score the set if either file's hash doesn't
   match what the manifest published (`atomic.py: atomic_publish_set`).
3. `evaluate` — compares `accepted.csv` + `review_queue.csv` against
   `ground_truth.json` and writes `evaluation_report.json`: per-field
   accuracy, the review-queue rate, and the auto-accepted receipts' rate
   of agreement with ground truth on every field this evaluator actually
   checks (see "Measured accuracy" for exactly which). It validates both
   CSVs' headers against the declared schema, refuses duplicate receipt
   ids inside a CSV or across the manifest, refuses an id that's in both
   CSVs or in neither, and refuses a manifest whose summary counts don't
   add up — before trusting a single row.

Row accounting always reconciles: every image discovered under the input
directory produces exactly one row in exactly one output CSV, and every
receipt lands in exactly one of three manifest outcomes — `accepted`,
`review` (a business-rule/confidence check failed), or `error` (the image
itself couldn't be opened or OCR'd: corrupt file, decode failure, a
declared Tesseract engine error, or a Tesseract timeout). An `error`
receipt still gets a `review_queue.csv` row with a categorised
`processing_error:<ExceptionType>` reason — never a silent skip and never
a crash that aborts the rest of the batch. `accepted + review + error ==
total_images` is asserted in `pipeline.py` and checked again independently
by `evaluate.py`. Two input files that would collide on the same receipt
id (e.g. `r1.png` and `r1.jpg`, since the id is the filename stem) are
refused before anything is published, rather than one silently
overwriting the other. `tests/test_failures.py` and
`tests/test_pipeline_reconciliation.py` check this directly.

## Setup

```bash
sudo apt-get install -y tesseract-ocr   # OCR engine (Apache-2.0); see LICENSES.md
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## One-command run

```bash
./run_demo.sh            # seed 7, 60 receipts
./run_demo.sh 7 60       # same, explicit
```

Writes `data/ground_truth/` (images + ground truth) and `data/output/`
(`accepted.csv`, `review_queue.csv`, `manifest.json`,
`evaluation_report.json`). `data/` is gitignored; nothing under it ships
in the repo.

## CLI, step by step

```bash
python3 -m receipt_ocr generate --out data/ground_truth --seed 7 --count 60
python3 -m receipt_ocr run --input data/ground_truth/images --out data/output
python3 -m receipt_ocr evaluate --out data/output --ground-truth data/ground_truth/ground_truth.json
```

## Tests

```bash
PYTHONPATH=src python3 -m pytest tests/ -q
```

61 tests: image-level generator determinism, the money/date/CSV-safety
grammar, field extraction against constructed OCR lines (including
malformed-line, conflicting-currency, ambiguous-total and low-confidence-
item cases), full-pipeline reconciliation against a real generated+OCR'd
corpus, and failure classes (corrupt file, simulated Tesseract engine
error and timeout, duplicate receipt ids, empty input directory,
formula-injection payloads).

## Measured accuracy — on this synthetic set only

Reproduce with:

```bash
./run_demo.sh 7 60
cat data/output/evaluation_report.json
```

On seed **7**, 60 generated receipts (one of six degradation variants
each, in rotation):

| Metric | Value |
|---|---|
| Review-queue rate | 41.7% (25 / 60) |
| Per-field accuracy — shop | 96.7% |
| Per-field accuracy — date | 83.3% |
| Per-field accuracy — total | 76.7% |
| Per-field accuracy — currency | 83.3% |
| Per-field accuracy — items (sum + count) | 61.7% |
| Auto-accepted receipts' scored-field agreement | 100% (35 / 35) |

Per-field accuracy is measured across **all** 60 receipts, whether they
were auto-accepted or sent to review — it's a measure of raw extraction
quality, not of what got published. "Auto-accepted receipts' scored-field
agreement" is the number that matters for the review-queue design: of the
receipts the pipeline was confident enough to auto-accept, all 35 agreed
with ground truth on every field `evaluate.py` actually checks — shop,
date, total, currency, and items (the **sum of item amounts and the item
count** only). It is **not** a claim that these 35 receipts were
reproduced completely correctly: item names, quantities and unit prices
are extracted (`extract.py: extract_items`) but not exported to the CSVs
or compared by the evaluator, so a receipt whose true items are entirely
different but happen to sum to the same total and count would still score
as agreeing here. Extending the evaluator to compare actual item records
would be needed to support a stronger claim; that extension is out of
scope for this demo. Tesseract's own word/line confidence is a heuristic
score from the engine, not a calibrated probability of correctness — the
0.75 threshold in `confidence.py` is a fixed cutoff, not a tuned
statistical bound. This is a small synthetic sample at one seed; it is not
a statistical guarantee, and it is not a claim about real scanned
receipts, which involve fonts, layouts and camera artefacts this
generator doesn't produce. Run `evaluate` on your own generated seeds to
see how the numbers move.

## How extraction works

- **Grammar is declared, not inferred.** Money must match
  `\d{1,3}(,\d{3})*\.\d{2}` (dot-decimal, exactly-3-digit thousands
  groups) or a bare `\d+\.\d{2}` — `1,25` (comma-decimal) and `1,2345.00`
  (bad grouping) are rejected outright, never reinterpreted
  (`schema.py: parse_money`). A currency symbol glued directly onto the
  amount (`$79.74`, common OCR output) is accepted if it's exactly one
  recognised marker; two conflicting markers on the same total line
  (`$10.00 EUR`) reject the currency field as `currency_conflict`, not a
  guess at which one is right (`schema.py: parse_money_with_symbol`).
- **Ambiguous totals are rejected, not resolved by picking one token.**
  `extract_total_and_currency` inspects *every* grammar-valid amount
  candidate on the declared total line, not just the rightmost one. If
  more than one distinct (amount, currency) candidate is found — two
  different amounts (`TOTAL $10.00 $12.00`), or the same amount glued to
  two different currency markers (`TOTAL $10.00 EUR10.00`, which is not
  "the same total twice" just because the numbers match) — the `total`
  field itself is rejected as `ambiguous_total:<candidates>` and sent to
  review, on top of whatever `currency_conflict` also fires
  (`extract.py`, `tests/test_extract.py`).
- **Dates** are matched against 4 declared formats (ISO, `d/m/Y`, `d-m-Y`,
  `d Mon Y`); anything else is `invalid_date`, not guessed at
  (`schema.py: DATE_FORMATS`).
- **Layout reconstruction, not Tesseract's block order.** A receipt's item
  name (left) and price (right) are far enough apart that Tesseract's own
  page-segmentation would read them as separate columns in block order,
  scrambling every item line. `ocr.py` instead reconstructs visual rows
  itself, purely from each word's vertical position, and only calls two
  words part of the same row when their vertical bands substantially
  overlap — a deliberately strict threshold, because merging two
  unrelated rows into one is the dangerous failure mode (see "Limits").
- **Reconciliation rule.** Line items must sum to the printed total
  (`total_mismatch` if not, tolerance 0.005 for rounding only — no sales
  tax is modelled, so a genuine mismatch means an extraction error, not
  tax math). An item line whose amount doesn't match the money grammar is
  recorded as `unparsed_item_line:<snippet>`, not dropped from
  consideration.
- **Confidence, checked per item, not just per field.** Each field's
  confidence comes from Tesseract's own word-level confidence for the
  token(s) it was read from (shop is also scaled by fuzzy-match ratio
  against the known shop names). A field below 0.75 confidence, or that
  fails its rule check, adds a named reason to the receipt. Item lines get
  the same 0.75 gate individually — `item_confidence_reasons` in
  `confidence.py` checks every parsed item's own OCR confidence, so one
  low-confidence item line (e.g. one badly-OCR'd price in an otherwise
  clean receipt) cannot be averaged away and auto-accepted just because
  the shop/date/total/currency fields and the other items are confident.
  Zero reasons across every field and every item means auto-accept
  (`confidence.py`).
- **Currency is kept per receipt, never converted.** Each receipt records
  whatever currency its own total line named; nothing sums or converts
  amounts across receipts of different currencies anywhere in this
  pipeline or its evaluation report. This is a single-receipt-at-a-time
  extraction tool, not an FX or multi-currency reconciliation tool.
- **Formula-injection-safe CSV.** Any field whose value starts with
  `= + - @` (or a stray tab/CR) is written with a leading `'` — the
  standard CSV convention for disarming formula auto-execution
  (`schema.py: csv_safe`). Tested as a string transform on the written
  cell (`tests/test_failures.py`); no spreadsheet application is opened
  as part of that test, so this is not a verified claim about how any
  specific program renders the result.

## Limits

- Shop matching covers the 4 fictional layouts in `shops.py`; a real
  client's vendor list would need its own name pool added, the same way a
  new invoice vendor needs its own label patterns in the PDF-invoice
  demo.
- No sales tax is modelled — each generated receipt's total is exactly
  the sum of its line items, so the total-vs-items reconciliation check
  is validating extraction fidelity, not tax arithmetic. A real receipt
  with tax would need that reconciliation rule extended to allow a
  declared tax line, which this demo does not implement.
- Rotation is capped at ±5° specifically because the item/price row
  reconstruction is position-based: at larger angles the price column can
  drift vertically by more than one row's height relative to the name
  column. The strict overlap threshold in `ocr.py` is chosen to fail safe
  in that case (the row fails to parse and the receipt goes to review)
  rather than silently attaching the wrong price to the wrong item name —
  but this pipeline does not deskew images before OCR, which a production
  version would need for scans rotated more than a few degrees.
- Currency detection recognises `$`/`USD`, `€`/`EUR`, `£`/`GBP` only
  (`schema.py: CURRENCY_MARKERS`); a receipt in another currency is
  correctly sent to review as `currency_not_found` rather than guessed.
- The confidence threshold (0.75) and mismatch tolerance (0.005) are
  fixed constants in `confidence.py`, not tuned against a larger labelled
  set — the measured numbers above are what those specific constants
  produce on this specific seed.
- This is OCR of printed synthetic receipt renders, not handwriting, and
  not real-world photographed receipts with folds, glare, staples or
  faded thermal print — the "measured accuracy" section above is scoped
  to exactly the synthetic set it was run on.

## Project layout

```
src/receipt_ocr/
  shops.py          fictional shop layouts, addresses and item catalogs
  models.py         LineItem / ReceiptGroundTruth / FieldExtraction / ExtractionResult
  schema.py         money/date grammar, currency markers, CSV header contracts,
                    formula-injection-safe CSV encoding
  atomic.py         atomic (write-temp, then rename) file publishing, plus
                    atomic_publish_set for the accepted/review/manifest triple
  generator.py       renders the deterministic synthetic corpus + ground truth
  preprocess.py      deterministic image preprocessing before OCR
  ocr.py             pytesseract wrapper (bounded by a timeout) + position-based
                    row reconstruction
  extract.py         shop/date/total/currency/items extraction against the grammar,
                    including ambiguous-total detection
  confidence.py       per-field and per-item threshold + rule-check classification
  pipeline.py         orchestrates the above; duplicate-id refusal; categorises
                    accepted/review/error outcomes; publishes the triple via
                    atomic_publish_set (prepare-then-commit, hash-bound at read
                    time -- not a single atomic transaction)
  evaluate.py         scores pipeline output against ground truth; validates
                    manifest/CSV consistency and content hashes before scoring
  cli.py             `generate` / `run` / `evaluate` subcommands
tests/              pytest suite (generator determinism, grammar/CSV-safety,
                    extraction unit tests, pipeline reconciliation, failure classes)
LICENSES.md         every open-source library/package used and its licence
```

## Role

Synthetic portfolio demonstration, implemented with AI coding agents and
independently reviewed by a separate AI reviewer. No client data or
client work.

An AI coding agent (Claude, Anthropic Sonnet) wrote this repository's
generator, pipeline, tests and README; an independent AI reviewer (a
separate Codex-based agent) is expected to run adversarial probes against
the built code and hold the repository until findings are fixed or a
claim is narrowed to match what the code actually does, the same process
used for this portfolio's other demos. All data is synthetic; no client
or employer code, data, or receipt layout was used anywhere in this
repository.
