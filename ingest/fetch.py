"""Fetch raw data (prices + announcements) for the portfolio into SQLite.

Run: python ingest/fetch.py [--days 30]
Each source fails independently: a blocked exchange must not stop prices, and vice versa.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from finn import db  # noqa: E402
from finn.config import PORTFOLIO  # noqa: E402
from finn.sources import nse, prices  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="announcement look-back window")
    args = ap.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    client = nse.NSEClient()
    price_fail, ann_fail = [], []

    with db.session() as conn:
        for sym in PORTFOLIO:
            try:
                n = prices.store_prices(conn, prices.fetch_prices(sym))
                if n == 0:
                    raise ValueError("no rows")
            except Exception as exc:  # noqa: BLE001
                price_fail.append(sym)
                print(f"price FAIL {sym}: {exc}")
            try:
                new = nse.store_announcements(conn, client.announcements(sym, start, end))
                print(f"{sym:<12} prices ok, {new} new announcements")
            except Exception as exc:  # noqa: BLE001
                ann_fail.append(sym)
                print(f"announcements FAIL {sym}: {exc}")
            conn.commit()

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if len(price_fail) < len(PORTFOLIO):
            db.set_meta(conn, "prices_fetched_at", now)
        if len(ann_fail) < len(PORTFOLIO):
            db.set_meta(conn, "announcements_fetched_at", now)
        total = conn.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"]

    print(f"\nannouncements in db: {total}; price failures: {price_fail or 'none'}; "
          f"announcement failures: {ann_fail or 'none'}")
    return 1 if (len(price_fail) == len(PORTFOLIO) and len(ann_fail) == len(PORTFOLIO)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
