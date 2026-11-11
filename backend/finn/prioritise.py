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


# Rupee amounts as they appear in filing summaries: "Rs. 2,62,000", "Rs 200 crores", "INR 70 billion".
AMOUNT = re.compile(r"(?:Rs\.?|INR|₹)\s*([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|million|billion)?", re.I)
TO_CRORE = {"crore": 1.0, "crores": 1.0, "cr": 1.0, "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01,
            "million": 0.1, "billion": 100.0}
SMALL_AMOUNT_CRORE = 1.0


def largest_amount_crore(text: str | None) -> float | None:
    """The largest rupee amount mentioned, in crore. None when no amount is stated."""
    found = []
    for number, unit in AMOUNT.findall(text or ""):
        try:
            value = float(number.replace(",", ""))
        except ValueError:
            continue
        found.append(value * TO_CRORE[unit.lower()] if unit else value / 1e7)
    return max(found) if found else None


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
          days: dict[str, dict], summary: str | None = None) -> tuple[float, list[str], dict | None]:
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

    # A penalty or demand that is trivially small for a listed company is paperwork, not news.
    if category == "litigation":
        amount = largest_amount_crore(summary)
        if amount is not None and amount < SMALL_AMOUNT_CRORE:
            value *= 0.4
            reasons.append("Amount involved is under ₹1 crore (x0.4)")

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
