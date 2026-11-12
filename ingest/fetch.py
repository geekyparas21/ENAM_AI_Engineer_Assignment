"""Fetch raw data (prices + announcements) for the portfolio into SQLite.

Run: python ingest/fetch.py [--days 30]
Each source fails independently: a blocked exchange must not stop prices, and vice versa.

Announcements take the whole-market NSE feed in one request and filter to the portfolio
locally, falling back to per-symbol calls only if that one request fails. Twenty requests
give NSE twenty chances to rate-limit a datacenter IP; one gives it one.
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


def fetch_announcements(conn, client: nse.NSEClient, start: date, end: date) -> tuple[int, list[str], str | None]:
    """Returns (new rows stored, symbols that failed, error to record if the feed was blocked)."""
    try:
        market = client.all_announcements(start, end)
        mine = [r for r in market if (r.get("symbol") or "").upper() in PORTFOLIO]
        new = nse.store_announcements(conn, mine)
        print(f"all-market feed: {len(market)} filings, {len(mine)} for the portfolio, {new} new")
        return new, [], None
    except Exception as exc:  # noqa: BLE001
        print(f"all-market feed FAILED ({exc}); falling back to per-symbol calls")
        feed_error = f"all-market feed: {exc}"

    new_total, failed = 0, []
    for sym in PORTFOLIO:
        try:
            n = nse.store_announcements(conn, client.announcements(sym, start, end))
            new_total += n
            print(f"  {sym:<12} {n} new")
        except Exception as exc:  # noqa: BLE001
            failed.append(sym)
            print(f"  announcements FAIL {sym}: {exc}")
    # Only a total per-symbol wipeout is worth recording as the run's error.
    return new_total, failed, feed_error if len(failed) == len(PORTFOLIO) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30, help="announcement look-back window")
    args = ap.parse_args()

    end = date.today()
    start = end - timedelta(days=args.days)
    client = nse.NSEClient()
    price_fail: list[str] = []

    with db.session() as conn:
        for sym in PORTFOLIO:
            try:
                n = prices.store_prices(conn, prices.fetch_prices(sym))
                if n == 0:
                    raise ValueError("no rows")
            except Exception as exc:  # noqa: BLE001
                price_fail.append(sym)
                print(f"price FAIL {sym}: {exc}")
        conn.commit()

        new_anns, ann_fail, ann_error = fetch_announcements(conn, client, start, end)
        conn.commit()

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        prices_ok = len(price_fail) < len(PORTFOLIO)
        anns_ok = len(ann_fail) < len(PORTFOLIO)
        if prices_ok:
            db.set_meta(conn, "prices_fetched_at", now)
        if anns_ok:
            db.set_meta(conn, "announcements_fetched_at", now)

        # The health endpoint reads these, so a blocked source is visible without the run log.
        db.set_meta(conn, "last_fetch_attempted_at", now)
        errors = []
        if not prices_ok:
            errors.append("every price fetch failed (yfinance unreachable)")
        if ann_error:
            errors.append(ann_error)
        elif not anns_ok:
            errors.append("every per-symbol announcement call failed (NSE blocked this runner)")
        elif price_fail:
            errors.append(f"prices missing for {', '.join(price_fail)}")
        db.set_meta(conn, "last_fetch_error", "; ".join(errors) if errors else "")
        if not errors:
            db.set_meta(conn, "last_fetch_ok_at", now)

        total = conn.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"]
        conn.commit()

    print(f"\nannouncements in db: {total} ({new_anns} new this run); "
          f"price failures: {price_fail or 'none'}; announcement failures: {ann_fail or 'none'}")
    return 1 if (not prices_ok and not anns_ok) else 0


if __name__ == "__main__":
    raise SystemExit(main())
