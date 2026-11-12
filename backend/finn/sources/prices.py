"""EOD price and volume from Yahoo Finance (.NS tickers)."""
from __future__ import annotations

import sqlite3

import yfinance as yf


def fetch_prices(symbol: str, period: str = "6mo") -> list[dict]:
    """Daily rows with % change and the trailing 20-session average volume.

    avg_vol_20 deliberately excludes the current session, so a volume spike is
    compared against the 20 days before it rather than diluting its own baseline.
    """
    hist = yf.Ticker(f"{symbol}.NS").history(period=period, interval="1d", auto_adjust=False)
    if hist.empty:
        return []
    # Yahoo publishes the newest session's volume before its close has settled, giving a
    # row with Volume > 0 but Close NaN. Such a row is not a session we can store or chart,
    # and dropping it before the shift/rolling maths keeps it out of the next day's
    # prev_close and the 20-day volume baseline.
    hist = hist[(hist["Volume"] > 0) & hist["Close"].notna()]
    if hist.empty:
        return []
    prev_close = hist["Close"].shift(1)
    pct = (hist["Close"] / prev_close - 1.0) * 100.0
    avg20 = hist["Volume"].shift(1).rolling(20).mean()
    rows = []
    for idx in hist.index:
        rows.append({
            "symbol": symbol,
            "date": idx.date().isoformat(),
            "close": round(float(hist.at[idx, "Close"]), 2),
            "prev_close": None if prev_close[idx] != prev_close[idx] else round(float(prev_close[idx]), 2),
            "pct_change": None if pct[idx] != pct[idx] else round(float(pct[idx]), 2),
            "volume": int(hist.at[idx, "Volume"]),
            "avg_vol_20": None if avg20[idx] != avg20[idx] else round(float(avg20[idx]), 0),
        })
    return rows


def store_prices(conn: sqlite3.Connection, rows: list[dict]) -> int:
    conn.executemany(
        "INSERT INTO prices (symbol, date, close, prev_close, pct_change, volume, avg_vol_20) "
        "VALUES (:symbol, :date, :close, :prev_close, :pct_change, :volume, :avg_vol_20) "
        "ON CONFLICT(symbol, date) DO UPDATE SET close = excluded.close, "
        "prev_close = excluded.prev_close, pct_change = excluded.pct_change, "
        "volume = excluded.volume, avg_vol_20 = excluded.avg_vol_20",
        rows,
    )
    return len(rows)
