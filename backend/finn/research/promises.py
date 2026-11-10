"""Promise Tracker: what management guided, call after call, against what was delivered.

Division of labour:
  cheap model   reads one transcript and lists explicit guidance statements with a
                verbatim quote and page;
  code          checks every quote really appears on that page (unverifiable quotes are
                dropped), and computes all delivered figures (financials.actuals);
  strong model  groups statements about the same target across calls into a thread and
                gives a verdict. It refers to delivered figures only by key; code fills in
                the numbers and re-checks any numeric verdict it can.
"""
from __future__ import annotations

import json
import re
import sqlite3

from .. import llm
from . import financials
from .corpus import doc_pages

VERDICTS = ("delivered", "missed", "moved_goalposts", "quietly_dropped", "in_progress", "unverifiable")
VERDICT_ORDER = {"missed": 0, "moved_goalposts": 1, "quietly_dropped": 2, "delivered": 3, "in_progress": 4,
                 "unverifiable": 5}
METRICS = ("revenue_growth", "revenue", "ebitda_margin", "ebit_margin", "pat_margin", "pat_growth", "pat",
           "capex", "cash_flow", "debt", "order_book", "other")
MAX_STATEMENTS_PER_CALL = 12
QUOTE_MATCH = 0.72
TOLERANCE = 0.5  # percentage points: figures are computed from rounded reported numbers

EXTRACT_SYSTEM = f"""You read the transcript of an Indian listed company's earnings call. Pages are marked [Page N].
List the explicit forward-looking guidance given by MANAGEMENT (never by analysts): targets, ranges or commitments
about revenue or growth, margins, profit, capex, cash flow, debt, order book or deal wins, capacity, headcount, or a
dated business milestone.

Include a statement only if it has a number or a clear timeframe. Skip general optimism, descriptions of the past,
and anything an analyst said. Prefer headline numbers. At most {MAX_STATEMENTS_PER_CALL} statements, most important first.

For each statement:
  metric     one of: {", ".join(METRICS)}
  label      short name for the target, e.g. "FY27 revenue growth" or "EBITDA margin"
  period     the period the target is for, e.g. "FY27", "Q3 FY27", "H2 FY27", "next 2-3 years"; null if not stated
  target     the target as stated, e.g. "18-22%", "at least 20.5%", "Rs 500 crore"
  low, high  the numeric bounds if stated (same number for a point target), else null
  unit       "%", "bps", "Rs crore", "USD million", or other unit as stated; null if none
  direction  one of: at_least, at_most, range, about, qualitative
  basis      one of: reported, constant_currency, organic, segment, other
  status     if management says so explicitly, one of: new, reiterated, raised, lowered, withdrawn; else null
  speaker    name or role if clear, else null
  quote      the exact words from the transcript that state it, copied verbatim, 12 to 45 words
  page       the page number where the quote appears

Reply with JSON only: {{"statements": [{{...}}]}}. If management gave no guidance, reply {{"statements": []}}."""

VERDICT_SYSTEM = """You analyse whether an Indian listed company's management did what it said it would.

You are given, in order:
  CALLS                the earnings calls, oldest first
  GUIDANCE STATEMENTS  what management said on each call, each with an id (verbatim quotes, already verified)
  DELIVERED FIGURES    figures computed from reported financials, each with a key

Group statements about the same target for the same period into a thread, so one thread shows how that target was
stated, repeated or changed across calls. Keep the threads that matter most to an investor, headline numbers first.
At most 10 threads. A statement belongs to at most one thread.

Verdict for each thread, exactly one of:
  delivered        the period is over and the delivered figure meets the final stated target
  missed           the period is over and the delivered figure falls short of the target
  moved_goalposts  before the period ended, a later call lowered the target, pushed out its date, or redefined it
  quietly_dropped  stated on an earlier call, then absent from every later call, and no delivered figure confirms it
  in_progress      the period is not over; set progress to ahead, on_track or behind using year-to-date figures
  unverifiable     no delivered figure matches this target (for example constant-currency or segment targets) and
                   later calls do not report against it

Rules:
  - Delivered numbers may come ONLY from DELIVERED FIGURES. Never write a delivered number yourself: put the key in
    actual_keys, and in the evidence text write it as a placeholder in braces, e.g. {FY26.revenue_growth}.
  - A figure marked (partial year) covers only part of the year: use it for in_progress, never for delivered or missed.
  - If the target's basis differs from the delivered figures (constant currency, organic, one segment), say so in
    the evidence and do not call it delivered or missed on reported figures alone.
  - Use nothing you know about the company beyond what is given here.
  - evidence: one sentence, at most 32 words, plain and specific. No adjectives like strong or impressive.

Reply with JSON only:
{"threads": [{
  "title": "short name, e.g. FY27 revenue growth",
  "metric": "revenue_growth | revenue | ebitda_margin | ebit_margin | pat_margin | pat_growth | pat | capex | cash_flow | debt | order_book | other",
  "period": "e.g. FY27",
  "statement_ids": ["oldest first"],
  "initial_target": "the target as first stated",
  "final_target": {"text": "the target as last stated", "low": number or null, "high": number or null, "unit": "% or other or null", "direction": "at_least | at_most | range | about | qualitative"},
  "basis": "reported | constant_currency | organic | segment | other",
  "actual_keys": ["keys from DELIVERED FIGURES, most relevant first; empty if none applies"],
  "verdict": "...",
  "progress": "ahead | on_track | behind | null",
  "evidence": "..."
}]}"""


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def quote_match(quote: str, text: str) -> float:
    """Share of the quote's word-trigrams found in the text: 1.0 is a verbatim match."""
    q, p = _words(quote), _words(text)
    if len(q) < 4:
        return 0.0
    grams = {tuple(q[i:i + 3]) for i in range(len(q) - 2)}
    page = {tuple(p[i:i + 3]) for i in range(len(p) - 2)}
    return len(grams & page) / len(grams)


def locate_quote(quote: str, pages: list[dict], claimed: int | None) -> int | None:
    """The page a quote really appears on, or None if it appears nowhere.

    The claimed page is tried first; a quote that runs over a page break is matched
    against two consecutive pages.
    """
    by_number = {p["page"]: p["text"] for p in pages}

    def score(page: int) -> float:
        return quote_match(quote, by_number.get(page, "") + " " + by_number.get(page + 1, ""))

    if claimed in by_number and score(claimed) >= QUOTE_MATCH:
        return claimed
    best = max(by_number, key=score, default=None)
    if best is not None and score(best) >= QUOTE_MATCH:
        return best
    return None


# An analyst restating guidance back to management ("you had said Q2 would be flattish") is not
# management guidance. Second-person address or a question is the tell.
ANALYST_SPEECH = re.compile(
    r"\byou(?: guys| all)? (?:had |have |did |also |earlier )?(?:said|spoke|spoken|mentioned|guided|talked|indicated|"
    r"alluded|highlighted|stated|called out)\b|\byour (?:guidance|commentary|aspiration|target|outlook)\b|"
    r"\b(?:can|could|would|will) you\b|\?\s*$", re.I)


def is_analyst_speech(quote: str) -> bool:
    return bool(ANALYST_SPEECH.search(quote.strip()))


PERIOD_TOKEN = re.compile(r"(?:(Q[1-4]|H[12]|9M)\s*)?(FY|CY)\s*'?(\d{2})(?:\d{2})?\b", re.I)


def period_key(period: str | None) -> str | None:
    """'Q2 FY27' -> 'Q2FY27', 'FY 2027' -> 'FY27'. None for open-ended periods like 'next 2-3 years'."""
    m = PERIOD_TOKEN.search(period or "")
    if not m:
        return None
    full = re.search(r"(FY|CY)\s*'?(\d{4})", period or "", re.I)
    year = full.group(2)[2:] if full else m.group(3)
    return f"{(m.group(1) or '').upper()}{m.group(2).upper()}{year}"


def same_period(actual_key: str, period: str | None) -> bool:
    """Is this delivered figure for the period the target is about? (FY27_YTD counts as FY27.)"""
    want = period_key(period)
    return want is not None and actual_key.split(".")[0].replace("_YTD", "") == want


def _num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.fullmatch(r"-?\d+(\.\d+)?", str(value).replace(",", "").strip())
    return float(m.group(0)) if m else None


def _text(value, limit: int = 300) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] if value and value.lower() not in {"null", "none", "n/a"} else None


def extract_call(conn: sqlite3.Connection, doc: dict, pages: list[dict]) -> tuple[list[dict], int]:
    """Guidance statements from one transcript. Returns (verified statements, dropped count)."""
    body = "\n\n".join(f"[Page {p['page']}]\n{p['text']}" for p in pages)
    prompt = f"Call: {doc['label']}\n\n{body}"
    result = llm.complete(conn, "extract_guidance", prompt, system=EXTRACT_SYSTEM, max_tokens=6000)
    raw = result.data.get("statements", []) if isinstance(result.data, dict) else []
    kept: list[dict] = []
    dropped = 0
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        quote, label = _text(item.get("quote"), 500), _text(item.get("label"), 90)
        if not quote or not label or is_analyst_speech(quote):
            dropped += 1
            continue
        page = locate_quote(quote, pages, int(item["page"]) if str(item.get("page", "")).isdigit() else None)
        if page is None:
            dropped += 1  # the model could not show where management said this
            continue
        metric = item.get("metric") if item.get("metric") in METRICS else "other"
        kept.append({
            "id": f"{doc['id']}-{len(kept) + 1}", "call": doc["id"], "metric": metric, "label": label,
            "period": _text(item.get("period"), 40), "target": _text(item.get("target"), 80),
            "low": _num(item.get("low")), "high": _num(item.get("high")), "unit": _text(item.get("unit"), 20),
            "direction": item.get("direction") if item.get("direction") in
            ("at_least", "at_most", "range", "about", "qualitative") else "qualitative",
            "basis": item.get("basis") if item.get("basis") in
            ("reported", "constant_currency", "organic", "segment", "other") else "reported",
            "status": item.get("status") if item.get("status") in
            ("new", "reiterated", "raised", "lowered", "withdrawn") else None,
            "speaker": _text(item.get("speaker"), 60), "quote": quote, "page": page,
        })
        if len(kept) >= MAX_STATEMENTS_PER_CALL:
            break
    return kept, dropped


def _met(target: dict, value: float) -> bool | None:
    """Does a delivered figure meet a numeric target? None when the target is not numeric."""
    low, high, direction = target.get("low"), target.get("high"), target.get("direction")
    if low is None and high is None:
        return None
    if direction == "at_most":
        bound = high if high is not None else low
        return value <= bound + TOLERANCE
    if direction == "about":
        centre = low if low is not None else high
        return abs(value - centre) <= max(1.0, 0.1 * abs(centre))
    floor = low if low is not None else high
    return value >= floor - TOLERANCE


def _progress(target: dict, value: float) -> str:
    low, high, direction = target.get("low"), target.get("high"), target.get("direction")
    if direction == "at_most":
        bound = high if high is not None else low
        return "on_track" if value <= bound + TOLERANCE else "behind"
    floor = low if low is not None else high
    ceiling = high if high is not None else low
    if value < floor - TOLERANCE:
        return "behind"
    return "ahead" if value > ceiling + TOLERANCE else "on_track"


def judge(conn: sqlite3.Connection, docs: list[dict], statements: list[dict], actuals: dict[str, dict]) -> list[dict]:
    """Group statements into threads with verdicts; validate everything the model returns."""
    if not statements:
        return []
    calls = [d for d in docs if d["kind"] == "transcript"][::-1]  # oldest first
    by_id = {s["id"]: s for s in statements}
    order = {d["id"]: i for i, d in enumerate(calls)}
    lines = ["CALLS (oldest first):"]
    lines += [f"  {d['id']}: {d['label']}" for d in calls]
    lines.append("\nGUIDANCE STATEMENTS:")
    for s in sorted(statements, key=lambda s: (order.get(s["call"], 0), s["id"])):
        lines.append(json.dumps({k: s[k] for k in ("id", "call", "metric", "label", "period", "target", "low", "high",
                                                   "unit", "direction", "basis", "status", "quote")},
                                ensure_ascii=False))
    lines.append("\nDELIVERED FIGURES:")
    for key, entry in actuals.items():
        partial = " (partial year)" if entry.get("partial") else ""
        lines.append(f"  {key} = {financials.format_actual(entry)}  [{entry['label']}]{partial}")
    result = llm.complete(conn, "promise_verdict", "\n".join(lines), system=VERDICT_SYSTEM, max_tokens=16000)
    raw = result.data.get("threads", []) if isinstance(result.data, dict) else []

    doc_by_id = {d["id"]: d for d in docs}
    used: set[str] = set()
    threads: list[dict] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        ids = [i for i in item.get("statement_ids", []) if i in by_id and i not in used]
        if not ids:
            continue  # a thread with no verified statement behind it is not shown
        used.update(ids)
        ids.sort(key=lambda i: (order.get(by_id[i]["call"], 0), i))
        keys = [k for k in item.get("actual_keys", []) if k in actuals]
        target_raw = item.get("final_target") if isinstance(item.get("final_target"), dict) else {}
        target = {
            "text": _text(target_raw.get("text"), 80) or by_id[ids[-1]]["target"],
            "low": _num(target_raw.get("low")), "high": _num(target_raw.get("high")),
            "unit": _text(target_raw.get("unit"), 20), "direction": target_raw.get("direction") or "qualitative",
        }
        verdict = item.get("verdict") if item.get("verdict") in VERDICTS else "unverifiable"
        progress = item.get("progress") if item.get("progress") in ("ahead", "on_track", "behind") else None
        basis = item.get("basis") if item.get("basis") in ("reported", "constant_currency", "organic", "segment",
                                                           "other") else "reported"
        checked = False

        # Re-check in code wherever the target is numeric and a matching reported figure exists.
        period = _text(item.get("period"), 40) or by_id[ids[-1]]["period"]
        primary = actuals[keys[0]] if keys else None
        on_period = bool(keys) and same_period(keys[0], period)
        comparable = (primary is not None and on_period and basis == "reported" and target["unit"] in ("%", None)
                      and primary["unit"] == "%" and (target["low"] is not None or target["high"] is not None))
        if comparable and verdict in ("delivered", "missed", "in_progress"):
            if primary.get("partial"):
                verdict, progress, checked = "in_progress", _progress(target, primary["value"]), True
            else:
                met = _met(target, primary["value"])
                if met is not None:
                    verdict, progress, checked = ("delivered" if met else "missed"), None, True
        elif primary is not None and primary.get("partial") and verdict in ("delivered", "missed"):
            verdict = "in_progress"  # a part-year figure cannot settle a full-year target
        if verdict in ("delivered", "missed") and keys and not on_period and period_key(period):
            verdict = "in_progress"  # the figure is for a different period than the target
        if verdict != "in_progress" or (keys and not on_period):
            progress = None  # no ahead/behind call on a target whose own period has no figures yet

        evidence = _text(item.get("evidence"), 400) or ""

        def fill(match: re.Match) -> str:
            entry = actuals.get(match.group(1))
            return financials.format_actual(entry) if entry else "an undisclosed figure"

        evidence = re.sub(r"\{([A-Za-z0-9_.']+)\}", fill, evidence)

        threads.append({
            "id": f"P{len(threads) + 1}",
            "title": _text(item.get("title"), 80) or by_id[ids[0]]["label"],
            "metric": item.get("metric") if item.get("metric") in METRICS else by_id[ids[0]]["metric"],
            "period": period,
            "verdict": verdict, "progress": progress, "checked_by_code": checked, "basis": basis,
            "initial_target": _text(item.get("initial_target"), 80) or by_id[ids[0]]["target"],
            "target": target, "evidence": evidence,
            "delivered": [{"key": k, "label": actuals[k]["label"], "text": financials.format_actual(actuals[k]),
                           "value": actuals[k]["value"], "unit": actuals[k]["unit"],
                           "partial": bool(actuals[k].get("partial")),
                           "on_period": same_period(k, period)} for k in keys[:3]],
            "history": [{
                "call": by_id[i]["call"], "call_label": doc_by_id[by_id[i]["call"]]["short"],
                "when": doc_by_id[by_id[i]["call"]]["period"], "target": by_id[i]["target"],
                "status": by_id[i]["status"], "speaker": by_id[i]["speaker"], "quote": by_id[i]["quote"],
                "page": by_id[i]["page"], "url": f"{doc_by_id[by_id[i]['call']]['url']}#page={by_id[i]['page']}",
            } for i in ids],
        })
    threads.sort(key=lambda t: VERDICT_ORDER[t["verdict"]])
    for n, t in enumerate(threads):
        t["id"] = f"P{n + 1}"
    return threads


def scorecard(threads: list[dict]) -> dict:
    counts = {v: sum(1 for t in threads if t["verdict"] == v) for v in VERDICTS}
    settled = counts["delivered"] + counts["missed"] + counts["moved_goalposts"] + counts["quietly_dropped"]
    return {
        "counts": counts, "total": len(threads), "settled": settled,
        # Of the promises that can be scored, how many were kept as originally stated.
        "kept_pct": round(100 * counts["delivered"] / settled) if settled else None,
    }


def build(conn: sqlite3.Connection, corpus: dict, actuals: dict[str, dict], progress=None) -> dict:
    calls = [d for d in corpus["docs"] if d["kind"] == "transcript" and not d.get("problem")]
    statements: list[dict] = []
    dropped = 0
    for n, doc in enumerate(calls):
        if progress:
            progress(f"Extracting guidance from {doc['short']}", n, len(calls) + 1)
        found, lost = extract_call(conn, doc, doc_pages(corpus, doc["id"]))
        statements += found
        dropped += lost
    if progress:
        progress("Comparing promises with delivered numbers", len(calls), len(calls) + 1)
    threads = judge(conn, corpus["docs"], statements, actuals)
    return {
        "calls": [{"id": d["id"], "label": d["label"], "short": d["short"], "url": d["url"]} for d in calls[::-1]],
        "threads": threads, "scorecard": scorecard(threads),
        "statements_found": len(statements), "statements_unverified": dropped,
    }
