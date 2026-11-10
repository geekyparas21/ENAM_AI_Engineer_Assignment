"""Research for one NSE ticker, end to end. Nothing here is specific to any company:
the same steps run for a ticker nobody pre-loaded.

  1. screener.in page  -> financial tables and document links
  2. documents         -> last 5 concall transcripts + latest annual report, read once, cached
  3. code              -> financial tabs and the table of delivered figures
  4. cheap model       -> guidance statements per transcript (quotes verified in code)
  5. strong model      -> promise verdicts; business snapshot, bull and bear (all cited)

The result is one JSON file per ticker. A second visit reads the file; nothing is recomputed.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable

from .. import llm
from ..sources import screener
from . import corpus as corpus_mod
from . import financials, narrative, promises

Progress = Callable[[str, int, int], None]
STEPS = 5


def facts_for(view: dict) -> list[str]:
    """Computed statements the model may cite as F-sources: direction plus the latest levels."""
    facts = list(view["observations"])
    annual, quarterly = view["annual"], view["quarterly"]
    if annual["years"]:
        y = annual["years"][-1]
        parts = [f"{y} revenue ₹{annual['revenue'][-1]:,.0f} cr"]
        if annual["revenue_growth"][-1] is not None:
            parts.append(f"growth {annual['revenue_growth'][-1]:.1f}%")
        if annual["ebitda_margin"][-1] is not None:
            parts.append(f"EBITDA margin {annual['ebitda_margin'][-1]:.1f}%")
        if annual["pat"][-1] is not None:
            parts.append(f"PAT ₹{annual['pat'][-1]:,.0f} cr")
        facts.append(", ".join(parts) + ".")
    if quarterly["periods"]:
        q = quarterly["periods"][-1]
        parts = [f"{q} revenue ₹{quarterly['revenue'][-1]:,.0f} cr"]
        if quarterly["revenue_yoy"][-1] is not None:
            parts.append(f"{quarterly['revenue_yoy'][-1]:+.1f}% YoY")
        if quarterly["ebitda_margin"][-1] is not None:
            parts.append(f"EBITDA margin {quarterly['ebitda_margin'][-1]:.1f}%")
        if quarterly["pat_yoy"][-1] is not None:
            parts.append(f"PAT {quarterly['pat_yoy'][-1]:+.1f}% YoY")
        facts.append(", ".join(parts) + ".")
    for h in view["headline"]:
        if h["label"] in ("ROCE", "ROE", "Debt / equity"):
            unit = "%" if h["unit"] == "%" else "x"
            facts.append(f"{h['label']}: {h['value']}{unit}.")
    return facts


def result_path(symbol: str):
    return corpus_mod.path_for(symbol) / "research.json"


def load(symbol: str) -> dict | None:
    path = result_path(symbol)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def available() -> list[dict]:
    """Tickers that already have a research file, for the picker."""
    out = []
    if corpus_mod.RESEARCH_DIR.exists():
        for folder in sorted(corpus_mod.RESEARCH_DIR.iterdir()):
            data = load(folder.name) if folder.is_dir() else None
            if data:
                card = data["promises"]["scorecard"]
                out.append({"symbol": data["symbol"], "name": data["name"], "generated_at": data["generated_at"],
                            "threads": card["total"], "kept_pct": card["kept_pct"]})
    return out


def build(conn: sqlite3.Connection, symbol: str, progress: Progress | None = None, refresh: bool = False) -> dict:
    symbol = symbol.upper().strip()

    def step(message: str, n: int) -> None:
        if progress:
            progress(message, n, STEPS)

    def sub(prefix_step: int):
        return (lambda message, i, total: progress(message, prefix_step, STEPS)) if progress else None

    before = llm.stats(conn)
    step("Finding the company's filings", 0)
    company = screener.company(symbol, refresh=refresh)

    step("Reading transcripts and the annual report", 1)
    corpus = None if refresh else corpus_mod.load(symbol)
    if corpus is None:
        corpus = corpus_mod.build(symbol, company, sub(1))
        corpus_mod.save(corpus)

    step("Computing the financial picture", 2)
    view = financials.view(company)
    actuals = financials.actuals(company)
    facts = facts_for(view)

    warnings = [f"{d['label']}: {d['problem']}" for d in corpus["docs"] if d.get("problem")]
    readable_calls = [d for d in corpus["docs"] if d["kind"] == "transcript" and not d.get("problem")]
    if not readable_calls:
        warnings.append("No readable concall transcripts were found, so there is no Promise Tracker for this company.")

    promise_view = {"calls": [], "threads": [], "scorecard": promises.scorecard([]),
                    "statements_found": 0, "statements_unverified": 0}
    story = {"business": None, "segments": [], "bull": [], "bear": [], "sources_used": 0}
    if llm.available("cheap") and llm.available("strong"):
        try:
            step("Extracting what management promised", 3)
            promise_view = promises.build(conn, corpus, actuals, sub(3))
        except llm.LLMError as exc:
            warnings.append(f"Promise Tracker could not be completed: {str(exc)[:160]}")
        try:
            step("Writing the business snapshot and the bull and bear cases", 4)
            story = narrative.build(conn, corpus, facts, company["name"])
        except llm.LLMError as exc:
            warnings.append(f"Business snapshot and bull/bear could not be completed: {str(exc)[:160]}")
    else:
        warnings.append("No model key configured: financial tabs only.")

    after = llm.stats(conn)
    cost_before, cost_after = before.get("cost_usd"), after.get("cost_usd")
    result = {
        "symbol": symbol, "name": company["name"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "docs": [{k: d.get(k) for k in ("id", "kind", "label", "short", "period", "url", "pages", "problem")}
                 for d in corpus["docs"]],
        "financials": view, "facts": facts, "promises": promise_view,
        "business": story["business"], "segments": story["segments"], "bull": story["bull"], "bear": story["bear"],
        "warnings": warnings,
        "usage": {
            "calls": after["calls"] - before["calls"], "cached": after["cached"] - before["cached"],
            "tokens": after["tokens"] - before["tokens"],
            "cost_usd": round(cost_after - cost_before, 4) if cost_before is not None and cost_after is not None else None,
        },
    }
    path = result_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    step("Done", STEPS)
    return result
