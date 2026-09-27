"""`generate` / `run` / `evaluate` subcommands."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="receipt_ocr")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="render synthetic receipt images + ground truth")
    p_gen.add_argument("--out", required=True)
    p_gen.add_argument("--seed", type=int, required=True)
    p_gen.add_argument("--count", type=int, default=40)

    p_run = sub.add_parser("run", help="OCR + extract a directory of receipt images")
    p_run.add_argument("--input", required=True, help="directory of receipt images")
    p_run.add_argument("--out", required=True, help="directory to write accepted.csv / review_queue.csv")

    p_eval = sub.add_parser("evaluate", help="score pipeline output against ground truth")
    p_eval.add_argument("--out", required=True, help="directory containing manifest.json/accepted.csv/review_queue.csv")
    p_eval.add_argument("--ground-truth", required=True)

    args = parser.parse_args(argv)

    if args.command == "generate":
        from .generator import generate

        records = generate(args.out, seed=args.seed, count=args.count)
        print(f"Generated {len(records)} synthetic receipts (seed={args.seed}) into {args.out}")
        return 0

    if args.command == "run":
        from .pipeline import process

        summary = process(args.input, args.out)
        print(json.dumps(summary, indent=2))
        return 0

    if args.command == "evaluate":
        from .evaluate import evaluate

        report = evaluate(args.out, args.ground_truth)
        print(json.dumps(report, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
