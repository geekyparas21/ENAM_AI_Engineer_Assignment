"""Ranking. Deterministic and explainable: every score comes with its reasons.

score = base weight of the category
        x kind modifier      (paperwork inside a material category is demoted)
        x role modifier      (management changes: CEO/CFO/auditor exits matter most)
        x market modifier    (the stock also moved unusually around the filing)

Personal modifiers (stars, mutes) are applied on the device, because settings are
stored per device and the Brief must rank correctly even when the backend is asleep.
"""
from __future__ import annotations

import re
from datetime import datetime

from .config import BASE_WEIGHT, MATERIAL_THRESHOLD

KIND_MODIFIER: dict[str, tuple[float, str]] = {
    "newspaper_ad": (0.1, "Newspaper ad confirming results, no new information"),
    "deck": (0.45, "Supporting deck/letter, the results filing itself ranks higher"),
    "intimation": (0.5, "Advance notice of a board meeting, not the outcome"),
    "repayment": (0.3, "Scheduled repayment of existing debt, not new funding"),
    "transcript": (1.0, ""),
}

TOP_ROLES = re.compile(
    r"\b(ceo|cfo|chief executive|chief financial|managing director|whole[- ]time director|"
    r"chairman|chairperson|statutory auditor|auditor)\b", re.I)
EXIT_WORDS = re.compile(r"\b(resign|cessation|ceased|step(s|ped)? down|removal)\b", re.I)
JUNIOR_ROLES = re.compile(r"senior management personnel|\bsmp\b", re.I)

# A filing counts as "accompanied by a market move" at these fixed levels. They are
# intentionally independent of the user's alert thresholds: ranking should not
# reshuffle when someone drags an alert slider.
MOVE_PCT = 3.0
MOVE_VOL_MULTIPLE = 2.0


def reaction_day(ts: str, trading_days: list[str]) -> str | None:
    """The session on which the market could first react to a filing.

    Filed before the 15:30 IST close on a trading day -> that day; otherwise the
    next session. Returns None if that session has not happened yet.
    """
    dt = datetime.fromisoformat(ts)
    day = dt.date().isoformat()
    after_close = (dt.hour, dt.minute) >= (15, 30)
    for d in trading_days:  # ascending
        if d > day or (d == day and not after_close):
            return d
    return None


def score(category: str, kind: str | None, subject: str, ts: str,
          days: dict[str, dict]) -> tuple[float, list[str], dict | None]:
    """Return (score, reasons, market_move). `days` maps date -> price row for the symbol."""
    base = BASE_WEIGHT.get(category, 5)
    value = float(base)
    reasons = [f"{category.replace('_', ' ')}: base {base}"]

    if kind and kind in KIND_MODIFIER:
        mult, why = KIND_MODIFIER[kind]
        if mult != 1.0:
            value *= mult
            reasons.append(f"{why} (x{mult:g})")

    if category == "management_change":
        if TOP_ROLES.search(subject) and EXIT_WORDS.search(subject):
            value *= 1.25
            reasons.append("Exit of a top executive or auditor (x1.25)")
        elif JUNIOR_ROLES.search(subject):
            value *= 0.7
            reasons.append("Below board/KMP level (x0.7)")

    move = None
    rday = reaction_day(ts, sorted(days))
    if rday and base >= MATERIAL_THRESHOLD:
        row = days[rday]
        pct = row.get("pct_change")
        ratio = row.get("vol_ratio")
        big_px = pct is not None and abs(pct) >= MOVE_PCT
        big_vol = ratio is not None and ratio >= MOVE_VOL_MULTIPLE
        if big_px or big_vol:
            value *= 1.25
            parts = []
            if big_px:
                parts.append(f"{pct:+.1f}%")
            if big_vol:
                parts.append(f"{ratio:.1f}x volume")
            reasons.append(f"Stock reacted on {rday}: {', '.join(parts)} (x1.25)")
            move = {"date": rday, "pct_change": pct, "vol_ratio": ratio}

    return round(value, 1), reasons, move
