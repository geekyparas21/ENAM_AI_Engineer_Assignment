"""Turn a material filing into a card. Lazy: a PDF is only fetched for items that earn one.

Results filings get the headline-numbers card. The model call that reads line items
off the P&L page is injected as `extract`, so this module runs (and is tested) without
any model: with no extractor, or when the filing cannot be read, the card falls back
to screener.in's standardised table and says so.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from . import documents
from .results import (build_card, card_from_screener, cross_check, find_results_page, infer_period,
                      summary_line)
from .sources import screener
from .titles import fiscal_period

Extractor = Callable[[str, str | None], dict]


def results_card(symbol: str, subject: str, ts: str, url: str | None,
                 extract: Extractor | None = None) -> tuple[dict | None, str]:
    """Return (card, path) where path is 'filing', 'screener' or 'none'."""
    period = fiscal_period(subject) or infer_period(ts)
    card: dict | None = None
    reason = "The filing has no attachment."

    if url:
        try:
            page_texts = documents.pages(url)
        except documents.DocumentError:
            reason = "The results PDF on the exchange could not be opened."
        else:
            hit = find_results_page(page_texts) if documents.has_text_layer(page_texts) else None
            if not documents.has_text_layer(page_texts):
                reason = "The results filing is an image-only scan."
            elif hit is None:
                reason = "No quarterly P&L table was found in the filing."
            elif extract is None:
                reason = "The filing has not been parsed yet."
            else:
                page_no, text, basis = hit
                try:
                    card = build_card(extract(text, basis), period, page_no)
                except Exception:  # noqa: BLE001 - any extraction failure falls back, never crashes ingest
                    reason = "The filing's table could not be read reliably."

    try:
        company = screener.company(symbol)
    except screener.ScreenerError:
        company = None

    if card is not None:
        if company is not None:
            card["checks"].extend(cross_check(card, company, period))
        return card, "filing"
    if company is not None:
        fallback = card_from_screener(company, period, reason)
        if fallback is not None:
            return fallback, "screener"
    return None, "none"


def enrich_results(conn: sqlite3.Connection, extract: Extractor | None = None,
                   redo_fallbacks: bool = False) -> dict[str, int]:
    """Build cards for results filings that do not have one yet.

    `redo_fallbacks` re-attempts filings whose card came from the screener fallback,
    which is how cards upgrade to filing-parsed once a model key is configured.
    """
    rows = conn.execute(
        "SELECT id, symbol, subject, ts, attachment_url, detail FROM announcements "
        "WHERE category = 'results' AND kind = 'filing'").fetchall()
    counts = {"filing": 0, "screener": 0, "none": 0, "kept": 0}
    for r in rows:
        existing = json.loads(r["detail"]) if r["detail"] else None
        if existing and not (redo_fallbacks and existing.get("source") == "screener"):
            counts["kept"] += 1
            continue
        card, path = results_card(r["symbol"], r["subject"] or "", r["ts"], r["attachment_url"], extract)
        counts[path] += 1
        if card is None:
            continue
        conn.execute("UPDATE announcements SET detail = ?, summary = ? WHERE id = ?",
                     (json.dumps(card, ensure_ascii=False), summary_line(card), r["id"]))
        conn.commit()
    return counts
