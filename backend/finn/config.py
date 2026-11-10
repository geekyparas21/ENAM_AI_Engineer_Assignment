"""Central configuration: paths, demo portfolio, categories and ranking weights."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# An empty FINN_DATA_DIR (as in a freshly copied .env) means "use the default", not "use cwd".
DATA_DIR = Path(os.environ.get("FINN_DATA_DIR", "").strip() or ROOT / "data")
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "finn.db"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
FRONTEND_SNAPSHOT_PATH = ROOT / "frontend" / "public" / "snapshot.json"

# Demo portfolio: all 20 verified on yfinance (.NS) on 2026-11-10, see ingest/verify_tickers.py
PORTFOLIO: dict[str, str] = {
    "RELIANCE": "Energy & Conglomerate",
    "HDFCBANK": "Banking",
    "INFY": "IT Services",
    "BHARTIARTL": "Telecom",
    "ITC": "FMCG",
    "LT": "Engineering & Construction",
    "SUNPHARMA": "Pharma",
    "ASIANPAINT": "Paints",
    "TITAN": "Jewellery & Retail",
    "ETERNAL": "Internet",
    "DMART": "Retail",
    "POLYCAB": "Cables & Electricals",
    "DIXON": "Electronics Manufacturing",
    "PERSISTENT": "IT Services",
    "KPITTECH": "Auto Software",
    "DEEPAKNTR": "Chemicals",
    "CDSL": "Capital Markets",
    "IRCTC": "Railways & Travel",
    "TATAPOWER": "Power",
    "ASTRAL": "Building Materials",
}

CATEGORIES = [
    "results", "M&A", "fund_raise", "management_change", "litigation", "insider_trading",
    "earnings_call", "investor_meetings", "credit_rating", "dividend", "bonus_split", "capex",
    "press_release", "postal_ballot", "agm_egm", "pledging", "unclassified",
]

# Base weight per category (0-100). High = material, low = routine.
BASE_WEIGHT: dict[str, int] = {
    "results": 90,
    "M&A": 85,
    "management_change": 80,
    "litigation": 75,
    "fund_raise": 75,
    "pledging": 75,
    "credit_rating": 60,
    "bonus_split": 55,
    "dividend": 50,
    "capex": 50,
    "insider_trading": 45,
    "press_release": 40,
    "earnings_call": 15,
    "investor_meetings": 10,
    "agm_egm": 10,
    "postal_ballot": 10,
    "unclassified": 5,
}

# Items scoring below this are collapsed into the "routine filings hidden" row.
MATERIAL_THRESHOLD = 35

DEFAULT_SETTINGS = {
    "volume_multiple": 2.0,
    "price_move_pct": 5.0,
    "alert_categories": [
        "results", "M&A", "management_change", "litigation", "fund_raise", "pledging",
        "credit_rating",
    ],
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
