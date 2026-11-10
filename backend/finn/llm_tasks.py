"""The model-backed steps of the push pipeline. Each one is narrow, returns JSON, and has
its output validated in code before anything is stored.

  classify_batch    stage 2 of classification: only what the rules could not place
  results_extractor line items off one P&L page (the maths lives in results.py)
  summarise         one line for a material filing, with its key number
  extract_people    who joined or left, their role, and the profile the filing carries
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from . import llm
from .config import CATEGORIES

BATCH_SIZE = 25
PAGE_CHARS = 14000
FILING_CHARS = 7000

CATEGORY_GUIDE = """results: quarterly/annual results, board meeting approving them, results decks, shareholder letters
M&A: acquisition, merger, demerger, joint venture, investing in or selling a stake in a subsidiary, IPO of a subsidiary
fund_raise: rights issue, QIP, preferential allotment, buyback, debt such as commercial paper or NCDs
management_change: a CEO, CFO, MD, director or other key manager joining, resigning or retiring
litigation: lawsuits, regulatory orders, fines, penalties, warnings, tax demands, insolvency proceedings
insider_trading: a promoter or insider buying or selling their own shareholding
earnings_call: the investor conference call: notice, transcript or recording
investor_meetings: meetings with specific investors or funds, investor conferences
credit_rating: a rating assigned, upgraded, downgraded or reaffirmed
dividend: a cash dividend declared, record date
bonus_split: bonus issue or stock split
capex: approval of spend on a new plant, facility or capacity expansion
press_release: order wins, new products, partnerships, rumour clarifications, media statements
postal_ballot: postal ballot notice or result
agm_egm: annual or extraordinary general meeting notice or result
pledging: a promoter pledging or releasing shares
unclassified: routine paperwork: ESOP grants, compliance certificates, ESG reports, auditor appointments, guarantees for subsidiaries, awards, CSR"""

CLASSIFY_SYSTEM = (
    "You label Indian stock-exchange filings. Choose exactly one category for each filing from this list:\n"
    + CATEGORY_GUIDE
    + '\nReply with JSON only: {"labels": [{"id": "<id>", "category": "<category>"}]}. '
      "Use only the subject text given. If it does not say enough to tell, use unclassified."
)


def classify_batch(conn: sqlite3.Connection, items: list[dict]) -> dict[str, str]:
    """items: [{'id', 'exch_category', 'subject'}] -> {id: category}. Unknown answers become unclassified."""
    out: dict[str, str] = {}
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        # Short local ids keep the prompt small; the exchange ids are long and meaningless to the model.
        local = {str(i + 1): item["id"] for i, item in enumerate(batch)}
        payload = [{"id": str(i + 1), "exchange_category": item["exch_category"], "subject": (item["subject"] or "")[:400]}
                   for i, item in enumerate(batch)]
        result = llm.complete(conn, "classify", json.dumps(payload, ensure_ascii=False),
                              system=CLASSIFY_SYSTEM, max_tokens=60 * len(batch) + 100)
        labels = result.data.get("labels", []) if isinstance(result.data, dict) else []
        for label in labels:
            if not isinstance(label, dict):
                continue
            real = local.get(str(label.get("id")))
            category = label.get("category")
            if real:
                out[real] = category if category in CATEGORIES else "unclassified"
        for real in local.values():
            out.setdefault(real, "unclassified")  # the model skipped it: never guess
    return out


# --- results extraction ----------------------------------------------------------------------

RESULTS_FIELDS = ("revenue", "other_income", "finance_costs", "depreciation",
                  "pbt_before_exceptional", "pbt", "tax", "pat")

RESULTS_SYSTEM = """You read one page of an Indian company's quarterly results filing: a profit and loss table.
The table has several columns. Use only these three:
  cur  = the latest quarter
  prev = the immediately preceding quarter
  yoy  = the same quarter one year earlier
Ignore half-year, nine-month and full-year columns.

Copy each figure exactly as printed. Do not calculate, round or convert. Brackets mean negative.
The text comes from OCR, so labels may be slightly misspelt. If a line is not on the page, use null.

Fields:
  revenue                 Revenue from operations (for banks: total interest earned)
  other_income            Other income
  finance_costs           Finance costs / interest expense (null for banks)
  depreciation            Depreciation and amortisation
  pbt_before_exceptional  Profit before exceptional items and tax (null if no exceptional items line)
  pbt                     Profit before tax
  tax                     Total tax expense
  pat                     Profit for the period after tax, before splitting into owners and minority

Reply with JSON only:
{"basis": "Consolidated" or "Standalone", "unit": "crore" | "lakh" | "million" | "billion" | "thousand",
 "cur": {fields}, "prev": {fields}, "yoy": {fields}}"""


def to_number(value: Any) -> float | None:
    """Coerce a printed figure to a float; None when it is not cleanly a number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("₹", "")
    negative = bool(re.fullmatch(r"[\(\[\{].*[\)\]\}]", text)) or text.startswith("-")
    text = text.strip("()[]{}-").strip()
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return None  # e.g. OCR artefacts like "11.102.55": better empty than wrong
    return -float(text) if negative else float(text)


def clean_results(data: Any, basis_hint: str | None) -> dict:
    if not isinstance(data, dict):
        raise llm.LLMError("results extraction did not return an object")
    out: dict[str, Any] = {
        "basis": data.get("basis") if data.get("basis") in ("Consolidated", "Standalone") else (basis_hint or "Reported"),
        "unit": str(data.get("unit", "")).lower(),
    }
    for col in ("cur", "prev", "yoy"):
        column = data.get(col) if isinstance(data.get(col), dict) else {}
        out[col] = {field: to_number(column.get(field)) for field in RESULTS_FIELDS}
    if out["cur"]["revenue"] is None or out["cur"]["pat"] is None:
        raise llm.LLMError("results extraction is missing revenue or PAT for the current quarter")
    return out


def results_extractor(conn: sqlite3.Connection):
    """Returns the callable enrich.results_card expects: (page_text, basis_hint) -> extracted dict."""
    def extract(page_text: str, basis_hint: str | None) -> dict:
        result = llm.complete(conn, "extract_results", page_text[:PAGE_CHARS],
                              system=RESULTS_SYSTEM, max_tokens=900)
        return clean_results(result.data, basis_hint)
    return extract


# --- one-line summaries ----------------------------------------------------------------------

SUMMARY_SYSTEM = """You write one line for an investor about a company filing, from the filing text only.
State what happened and the single most important number (rupee amount, stake %, ratio, rating, date).
At most 24 words. No opinion, no adjectives like significant or strategic, no company name (it is shown separately).
If the text does not contain enough to say what happened, reply with summary null.
Reply with JSON only: {"summary": "<line or null>", "amount_cr": <deal or issue size in Rs crore as a number, or null>}"""


def summarise(conn: sqlite3.Connection, category: str, title: str, text: str) -> dict | None:
    prompt = f"Filing type: {category}\nSubject: {title}\n\nFiling text:\n{text[:FILING_CHARS]}"
    result = llm.complete(conn, "summarise", prompt, system=SUMMARY_SYSTEM, max_tokens=200)
    data = result.data if isinstance(result.data, dict) else {}
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip() or summary.strip().lower() == "null":
        return None
    words = summary.split()
    return {"summary": " ".join(words[:30]), "amount_cr": to_number(data.get("amount_cr"))}


# --- management changes ----------------------------------------------------------------------

PEOPLE_SYSTEM = """You read an Indian company's exchange filing about a change in directors or senior management.
List each person affected. Use only what the filing says; SEBI requires appointment filings to carry a brief
profile of the appointee, so look for it (often in an annexure).

For each person:
  name       as written, without honorifics like Mr./Ms./Shri/Dr.
  role       the position, e.g. "Chief Financial Officer", "Independent Director"
  action     one of: appointed, re-appointed, resigned, retired, ceased, redesignated
  effective  the effective date as written, or null
  bio        2 short sentences from the filing's profile: previous employers, years of experience, education.
             null if the filing gives no profile. Never add anything not in the filing.
  reason     for exits only: the stated reason in a few words, else null

Reply with JSON only: {"people": [{...}]}. If the filing names nobody, reply {"people": []}."""

ACTIONS = {"appointed", "re-appointed", "resigned", "retired", "ceased", "redesignated"}


def extract_people(conn: sqlite3.Connection, title: str, text: str) -> list[dict]:
    prompt = f"Subject: {title}\n\nFiling text:\n{text[:FILING_CHARS]}"
    result = llm.complete(conn, "extract_people", prompt, system=PEOPLE_SYSTEM, max_tokens=900)
    raw = result.data.get("people", []) if isinstance(result.data, dict) else []
    people = []
    for p in raw if isinstance(raw, list) else []:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"].strip():
            continue

        def field(key: str) -> str | None:
            value = p.get(key)
            return value.strip() if isinstance(value, str) and value.strip() and value.strip().lower() != "null" else None

        action = (field("action") or "").lower()
        people.append({
            "name": re.sub(r"^(mr|mrs|ms|shri|smt|dr|prof)\.?\s+", "", p["name"].strip(), flags=re.I),
            "role": field("role") or "Role not stated",
            "action": action if action in ACTIONS else "changed",
            "effective": field("effective"),
            "bio": field("bio"),
            "bio_source": "the filing" if field("bio") else None,
            "bio_url": None,
            "reason": field("reason"),
        })
    return people
