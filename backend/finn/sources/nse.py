"""Corporate announcements from the NSE corporate-filings API.

NSE needs a browser-like session: load the homepage once to receive cookies, then
call the JSON API with the same session. BSE's API refused our requests outright
(403, re-confirmed from a residential IP with and without homepage priming), so NSE
is the only source; see docs/BUILD_LOG.md.

Prefer `all_announcements`: the same endpoint without a `symbol` returns the whole
market for the date range in ONE request, which we filter locally. Twenty per-symbol
calls give NSE twenty chances to rate-limit a datacenter IP; one call gives it one.
`announcements` remains as the per-symbol fallback.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import date, datetime

import requests

from ..config import USER_AGENT

HOME = "https://www.nseindia.com/"
API = "https://www.nseindia.com/api/corporate-announcements"


class NSEClient:
    def __init__(self, pause: float = 0.6) -> None:
        self.pause = pause
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
        })
        self._primed = False

    def _prime(self) -> None:
        self.session.get(HOME, timeout=30).raise_for_status()
        self._primed = True

    def _fetch(self, params: dict, what: str, timeout: int) -> list[dict]:
        if not self._primed:
            self._prime()
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(API, params=params, timeout=timeout)
                if resp.status_code in (401, 403):
                    self._prime()  # cookie expired: refresh once and retry
                    raise requests.HTTPError(f"NSE {resp.status_code}")
                resp.raise_for_status()
                time.sleep(self.pause)
                # The all-market feed carries thousands of rows from across the exchange.
                # One unparseable date there must not cost us the whole fetch.
                out = []
                for row in resp.json():
                    try:
                        out.append(normalise(row))
                    except Exception:  # noqa: BLE001,PERF203
                        continue
                return out
            except Exception as exc:  # noqa: BLE001 - retried, then surfaced
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"NSE announcements failed for {what}: {last_exc}")

    def all_announcements(self, start: date, end: date) -> list[dict]:
        """Every equity filing in the range, in one request. Filter to a portfolio locally."""
        return self._fetch(
            {"index": "equities",
             "from_date": start.strftime("%d-%m-%Y"),
             "to_date": end.strftime("%d-%m-%Y")},
            "the whole market", timeout=90)

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        return self._fetch(
            {"index": "equities", "symbol": symbol,
             "from_date": start.strftime("%d-%m-%Y"),
             "to_date": end.strftime("%d-%m-%Y")},
            symbol, timeout=30)


def normalise(row: dict) -> dict:
    ts = datetime.strptime(row["an_dt"], "%d-%b-%Y %H:%M:%S")
    return {
        "id": f"NSE-{row['seq_id']}",
        "symbol": row["symbol"],
        "company": (row.get("sm_name") or "").strip(),
        "ts": ts.isoformat() + "+05:30",
        "exch_category": (row.get("desc") or "").strip(),
        "subject": " ".join((row.get("attchmntText") or "").split()),
        "attachment_url": row.get("attchmntFile") or None,
        "source": "NSE",
    }


def store_announcements(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insert new filings only; existing rows keep their classification and detail."""
    before = conn.total_changes
    conn.executemany(
        "INSERT OR IGNORE INTO announcements "
        "(id, symbol, company, ts, exch_category, subject, attachment_url, source) "
        "VALUES (:id, :symbol, :company, :ts, :exch_category, :subject, :attachment_url, :source)",
        rows,
    )
    return conn.total_changes - before
