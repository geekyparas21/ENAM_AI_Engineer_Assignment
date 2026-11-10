"""Turn exchange boilerplate into a short, readable card title. Pure string work, no LLM."""
from __future__ import annotations

import re

PREFIX = re.compile(
    r"^.{0,120}?\bhas\s+(informed|submitted|filed with)\s+(to\s+)?(the\s+)?exchange,?\s*"
    r"(a copy\s+)?(regarding|about|on|that|of)?\s*(the\s+)?", re.I)
MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
          "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
PERIOD = re.compile(
    r"ended\s+(?:on\s+)?(?:(\d{1,2})(?:st|nd|rd|th)?\s+)?([A-Za-z]+)\s*(?:(\d{1,2}),?\s*)?,?\s*(\d{4})", re.I)


def fiscal_period(text: str) -> str | None:
    """'...quarter ended September 30, 2026' -> 'Q2 FY27' (Indian fiscal year, April-March)."""
    m = PERIOD.search(text or "")
    if not m:
        return None
    month = MONTHS.get(m.group(2).lower())
    if month not in (3, 6, 9, 12):
        return None
    year = int(m.group(4))
    quarter = {6: 1, 9: 2, 12: 3, 3: 4}[month]
    fy = year + 1 if month != 3 else year
    return f"Q{quarter} FY{fy % 100:02d}"


def clean_title(subject: str, exch_category: str) -> str:
    text = " ".join((subject or "").split())
    text = PREFIX.sub("", text, count=1)
    text = PREFIX.sub("", text, count=1)  # some filings repeat the boilerplate twice
    text = text.strip(" '\"`.")
    text = re.sub(r"'{2,}", "'", text)
    if not text or text.lower() in {"updates", "general updates"}:
        text = exch_category or "Filing"
    return text[0].upper() + text[1:]
