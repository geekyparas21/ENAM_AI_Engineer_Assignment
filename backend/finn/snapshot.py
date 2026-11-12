"""Build the processed view the app reads: classified, ranked filings plus market data.

The same dict is served by the API and written to disk as the committed seed
snapshot, so the app has real data even when every live source is down.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import db, llm
from .alerts import vol_ratio
from .classify import AMBIGUOUS, classify
from .config import (BASE_WEIGHT, DEFAULT_SETTINGS, FRONTEND_SNAPSHOT_PATH, MATERIAL_THRESHOLD,
                     PORTFOLIO, SNAPSHOT_PATH)
from .prioritise import score
from .titles import clean_title, fiscal_period

MARKET_DAYS = 30


def classify_pending(conn: sqlite3.Connection) -> dict:
    """Stage 1 (rules) for every unclassified row. Returns counts for the cost report."""
    rows = conn.execute(
        "SELECT id, exch_category, subject FROM announcements WHERE category IS NULL").fetchall()
    counts = {"rule": 0, "ambiguous": 0}
    for r in rows:
        v = classify(r["exch_category"], r["subject"])
        if v.category == AMBIGUOUS:
            counts["ambiguous"] += 1
            conn.execute("UPDATE announcements SET category = ?, cat_method = 'pending', cat_rule = ? "
                         "WHERE id = ?", (AMBIGUOUS, v.rule, r["id"]))
        else:
            counts["rule"] += 1
            conn.execute("UPDATE announcements SET category = ?, cat_method = 'rule', cat_rule = ?, "
                         "kind = ? WHERE id = ?", (v.category, v.rule, v.kind, r["id"]))
    return counts


def market_rows(conn: sqlite3.Connection, symbol: str, limit: int = MARKET_DAYS) -> list[dict]:
    rows = conn.execute(
        "SELECT symbol, date, close, prev_close, pct_change, volume, avg_vol_20 FROM prices "
        "WHERE symbol = ? ORDER BY date DESC LIMIT ?", (symbol, limit)).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        d["vol_ratio"] = vol_ratio(d["volume"], d["avg_vol_20"])
        out.append(d)
    return out


def build(conn: sqlite3.Connection) -> dict:
    market = {sym: market_rows(conn, sym) for sym in PORTFOLIO}
    names: dict[str, str] = {}

    anns = []
    for r in conn.execute("SELECT * FROM announcements ORDER BY ts DESC").fetchall():
        a = dict(r)
        names.setdefault(a["symbol"], a["company"])
        # Rows still waiting for the LLM are shown as unclassified, never guessed.
        category = a["category"] if a["category"] in BASE_WEIGHT else "unclassified"
        days = {d["date"]: d for d in market.get(a["symbol"], [])}
        s, reasons, move = score(category, a["kind"], a["subject"] or "", a["ts"], days, a["summary"])
        anns.append({
            "id": a["id"],
            "symbol": a["symbol"],
            "company": a["company"],
            "ts": a["ts"],
            "exch_category": a["exch_category"],
            "subject": a["subject"],
            "title": clean_title(a["subject"], a["exch_category"]),
            "period": fiscal_period(a["subject"]) if category == "results" else None,
            "url": a["attachment_url"],
            "source": a["source"],
            "category": category,
            "kind": a["kind"],
            "method": a["cat_method"],
            "score": s,
            "reasons": reasons,
            "move": move,
            "summary": a["summary"],
            "detail": json.loads(a["detail"]) if a["detail"] else None,
        })

    portfolio = []
    for sym, sector in PORTFOLIO.items():
        rows = market[sym]
        last = rows[-1] if rows else {}
        portfolio.append({
            "symbol": sym,
            "company": names.get(sym, sym),
            "sector": sector,
            "date": last.get("date"),
            "close": last.get("close"),
            "pct_change": last.get("pct_change"),
            "volume": last.get("volume"),
            "avg_vol_20": last.get("avg_vol_20"),
            "vol_ratio": last.get("vol_ratio"),
            "spark": [d["close"] for d in rows],
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": {
            "prices": db.get_meta(conn, "prices_fetched_at"),
            "announcements": db.get_meta(conn, "announcements_fetched_at"),
            "last_session": max((p["date"] for p in portfolio if p["date"]), default=None),
        },
        # Ingest health, so /health and the "data as of" line can tell a successful
        # refresh apart from a blocked one without reading the workflow log.
        "ingest": {
            "last_ok_at": db.get_meta(conn, "last_fetch_ok_at"),
            "last_attempted_at": db.get_meta(conn, "last_fetch_attempted_at"),
            "last_error": db.get_meta(conn, "last_fetch_error") or None,
        },
        "material_threshold": MATERIAL_THRESHOLD,
        "defaults": DEFAULT_SETTINGS,
        "portfolio": portfolio,
        "market": market,
        "announcements": anns,
        # What the model steps cost to produce this data, with the per-task breakdown.
        "stats": llm.stats(conn),
    }


def refresh_ingest_meta(conn: sqlite3.Connection) -> bool:
    """Update only the ingest block of the snapshot already on disk.

    A run that could not reach a source has no new data to publish, but it must still
    report why. Without this the failure is invisible: the snapshot keeps its old
    ingest block and /health goes on saying "ok" over data nothing refreshed.
    """
    if not SNAPSHOT_PATH.exists():
        return False
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    attempted = db.get_meta(conn, "last_fetch_attempted_at")
    # A runner starts with an empty database, so a failed run knows of no successful
    # fetch. That is ignorance, not evidence, and it must not erase the real time the
    # data last landed — which is the one figure /health and the footer are built on.
    previous_ok = (snap.get("ingest") or {}).get("last_ok_at")
    snap["ingest"] = {
        "last_ok_at": db.get_meta(conn, "last_fetch_ok_at") or previous_ok,
        "last_attempted_at": attempted,
        # No attempt recorded at all means the fetch step itself did not finish.
        "last_error": (db.get_meta(conn, "last_fetch_error") or None) if attempted
                      else "the fetch step did not complete",
    }
    write(snap)
    return True


def write(snapshot: dict) -> None:
    text = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    for path in (SNAPSHOT_PATH, FRONTEND_SNAPSHOT_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
