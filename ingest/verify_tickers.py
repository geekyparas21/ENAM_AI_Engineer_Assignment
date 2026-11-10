"""Verify every candidate ticker resolves on yfinance (.NS) and has recent EOD data.

Run: python ingest/verify_tickers.py
Prints one line per ticker; exits non-zero if any fail.
"""
import sys

import yfinance as yf

CANDIDATES = [
    "RELIANCE", "HDFCBANK", "INFY", "BHARTIARTL", "ITC", "LT", "SUNPHARMA",
    "ASIANPAINT", "TITAN", "ETERNAL", "DMART", "POLYCAB", "DIXON", "PERSISTENT",
    "KPITTECH", "DEEPAKNTR", "CDSL", "IRCTC", "TATAPOWER", "ASTRAL",
]


def main() -> int:
    tickers = sys.argv[1:] or CANDIDATES
    failed = []
    for sym in tickers:
        try:
            hist = yf.Ticker(f"{sym}.NS").history(period="3mo", interval="1d", auto_adjust=False)
            if hist.empty or len(hist) < 21:
                raise ValueError(f"only {len(hist)} rows")
            last = hist.iloc[-1]
            print(f"OK   {sym:<12} rows={len(hist):<3} last={hist.index[-1].date()} "
                  f"close={last['Close']:.2f} vol={int(last['Volume'])}")
        except Exception as exc:  # noqa: BLE001 - report every failure
            failed.append(sym)
            print(f"FAIL {sym:<12} {exc}")
    print(f"\n{len(tickers) - len(failed)}/{len(tickers)} resolved; failed: {failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
