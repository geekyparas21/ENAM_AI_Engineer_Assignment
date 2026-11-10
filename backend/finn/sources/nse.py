"""Corporate announcements from the NSE corporate-filings API.

NSE needs a browser-like session: load the homepage once to receive cookies, then
call the JSON API with the same session. BSE's API refused our requests outright
(403), so NSE is the primary source; see docs/BUILD_LOG.md.
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

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        if not self._primed:
            self._prime()
        params = {
            "index": "equities",
            "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"),
            "to_date": end.strftime("%d-%m-%Y"),
        }
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(API, params=params, timeout=30)
                if resp.status_code in (401, 403):
                    self._prime()  # cookie expired: refresh once and retry
                    raise requests.HTTPError(f"NSE {resp.status_code}")
                resp.raise_for_status()
                time.sleep(self.pause)
                return [normalise(row) for row in resp.json()]
            except Exception as exc:  # noqa: BLE001 - retried, then surfaced
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"NSE announcements failed for {symbol}: {last_exc}")


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
