"""Classifier evaluation on a hand-labelled sample of real filings.

Run: python evals/run_eval.py

Compares two pipelines on evals/labelled.csv:
  rules only      stage 1 alone; a filing the rules cannot place counts as wrong
  rules + model   the shipped pipeline (stage 1, then the cheap model for the remainder),
                  read from the committed snapshot so the result is reproducible offline
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from finn.classify import AMBIGUOUS, classify  # noqa: E402


def main() -> int:
    rows = list(csv.DictReader((ROOT / "evals" / "labelled.csv").open(encoding="utf-8")))
    snapshot = json.loads((ROOT / "data" / "snapshot.json").read_text(encoding="utf-8"))
    shipped = {a["id"]: (a["category"], a["method"]) for a in snapshot["announcements"]}

    rules_right = placed = placed_right = full_right = model_n = model_right = 0
    misses: list[tuple[str, str, str, str, str]] = []
    for r in rows:
        gold = r["gold"]
        stage1 = classify(r["exchange_category"], r["subject"]).category
        final, method = shipped[r["id"]]
        if stage1 != AMBIGUOUS:
            placed += 1
            placed_right += stage1 == gold
        rules_right += stage1 == gold
        full_right += final == gold
        if method == "llm":
            model_n += 1
            model_right += final == gold
        if final != gold:
            misses.append((r["symbol"], gold, final, method or "", r["subject"][:80]))

    n = len(rows)
    print(f"sample: {n} filings ({placed} placed by rules, {n - placed} left for the model)")
    print(f"rules only        : {rules_right}/{n} = {100 * rules_right / n:.1f}%  "
          f"(precision on what rules place: {placed_right}/{placed} = {100 * placed_right / placed:.1f}%)")
    print(f"rules + model     : {full_right}/{n} = {100 * full_right / n:.1f}%")
    print(f"model on its share: {model_right}/{model_n} = {100 * model_right / max(model_n, 1):.1f}%")
    print(f"\ngold label mix: {dict(Counter(r['gold'] for r in rows).most_common())}")
    print(f"\n{len(misses)} misses of the shipped pipeline (gold <- predicted, by):")
    for sym, gold, pred, method, subject in misses:
        print(f"  {sym:<10} {gold:<17} <- {pred:<17} {method:<5} {subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
