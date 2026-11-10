"""Threshold alerts. Pure functions over stored EOD rows, so they are trivially testable.

The baseline is always shown: an alert says what crossed, by how much, versus what.
"""
from __future__ import annotations


def vol_ratio(volume: int | None, avg_vol_20: float | None) -> float | None:
    if not volume or not avg_vol_20:
        return None
    return round(volume / avg_vol_20, 2)


def evaluate_day(row: dict, volume_multiple: float, price_move_pct: float) -> list[dict]:
    """Alerts fired by one symbol-day. `row` has symbol, date, close, prev_close,
    pct_change, volume, avg_vol_20."""
    fired = []
    pct = row.get("pct_change")
    if pct is not None and abs(pct) >= price_move_pct:
        fired.append({
            "type": "price",
            "symbol": row["symbol"],
            "date": row["date"],
            "value": pct,
            "threshold": price_move_pct,
            "baseline": row.get("prev_close"),
            "close": row.get("close"),
            "text": f"{pct:+.2f}% on the day (threshold {price_move_pct:g}%)",
        })
    ratio = vol_ratio(row.get("volume"), row.get("avg_vol_20"))
    if ratio is not None and ratio >= volume_multiple:
        fired.append({
            "type": "volume",
            "symbol": row["symbol"],
            "date": row["date"],
            "value": ratio,
            "threshold": volume_multiple,
            "baseline": row.get("avg_vol_20"),
            "volume": row.get("volume"),
            "text": f"Volume {ratio:.1f}x its 20-day average (threshold {volume_multiple:g}x)",
        })
    return fired


def evaluate(rows: list[dict], volume_multiple: float = 2.0, price_move_pct: float = 5.0) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        out.extend(evaluate_day(row, volume_multiple, price_move_pct))
    return sorted(out, key=lambda a: (a["date"], abs(a["value"])), reverse=True)
