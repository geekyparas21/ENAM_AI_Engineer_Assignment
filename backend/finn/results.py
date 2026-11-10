"""Results card maths. The model only reads line items off the page; every derived
number here (EBITDA, margins, QoQ, YoY) is computed in code and cross-checked.

EBITDA definition used throughout (operating view):
    EBITDA = PBT (before exceptional items) + finance costs + depreciation & amortisation
             - other income
Banks and other lenders have no meaningful EBITDA (interest is their raw material),
so when finance costs or depreciation are absent the EBITDA rows are left empty.
"""
from __future__ import annotations

import re

import pymupdf

COLUMNS = ("cur", "prev", "yoy")
EBITDA_DEFINITION = "EBITDA = PBT before exceptionals + finance costs + D&A − other income."

# Everything is shown in Rs crore so cards are comparable across companies.
UNIT_TO_CRORE = {"crore": 1.0, "crores": 1.0, "cr": 1.0, "million": 0.1, "millions": 0.1, "mn": 0.1,
                 "lakh": 0.01, "lakhs": 0.01, "lacs": 0.01, "billion": 100.0, "thousand": 0.0001}


def pct_change(cur: float | None, base: float | None) -> float | None:
    """Growth in %. Undefined when the base is zero or negative (a swing from loss to
    profit is not a percentage), so the card shows a dash instead of a misleading number."""
    if cur is None or base is None or base <= 0:
        return None
    return round((cur / base - 1.0) * 100.0, 1)


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _metric(values: dict[str, float | None]) -> dict:
    """Growth is computed on unrounded values; rounding happens only for display."""
    return {
        "cur": _r(values["cur"]), "prev": _r(values["prev"]), "yoy": _r(values["yoy"]),
        "qoq_pct": pct_change(values["cur"], values["prev"]),
        "yoy_pct": pct_change(values["cur"], values["yoy"]),
    }


def _margin(num: dict[str, float | None], den: dict[str, float | None]) -> dict:
    m = {c: (round(100.0 * num[c] / den[c], 1) if num[c] is not None and den[c] else None) for c in COLUMNS}
    diff = lambda a, b: round(a - b, 1) if a is not None and b is not None else None  # noqa: E731
    # For margins the deltas are percentage points, not percent of a percent.
    return {"cur": m["cur"], "prev": m["prev"], "yoy": m["yoy"],
            "qoq_pct": diff(m["cur"], m["prev"]), "yoy_pct": diff(m["cur"], m["yoy"])}


def build_card(extracted: dict, period: str | None = None, page: int | None = None) -> dict:
    """`extracted` is the model's JSON:
    {"basis": "Consolidated", "unit": "million",
     "cur": {"revenue":..,"other_income":..,"finance_costs":..,"depreciation":..,
             "pbt_before_exceptional":..,"pbt":..,"tax":..,"pat":..}, "prev": {...}, "yoy": {...}}
    """
    scale = UNIT_TO_CRORE.get(str(extracted.get("unit", "")).strip().lower())
    checks: list[dict] = []
    if scale is None:
        scale = 1.0
        checks.append({"name": "unit", "ok": False,
                       "note": f"Unit '{extracted.get('unit')}' not recognised; figures shown as filed."})

    def col(field: str) -> dict[str, float | None]:
        out = {}
        for c in COLUMNS:
            v = (extracted.get(c) or {}).get(field)
            out[c] = None if v is None else float(v) * scale
        return out

    revenue, other, fin, dep = col("revenue"), col("other_income"), col("finance_costs"), col("depreciation")
    pbt, pbt_pre, tax, pat = col("pbt"), col("pbt_before_exceptional"), col("tax"), col("pat")

    ebitda: dict[str, float | None] = {}
    for c in COLUMNS:
        base = pbt_pre[c] if pbt_pre[c] is not None else pbt[c]
        if base is None or fin[c] is None or dep[c] is None:
            ebitda[c] = None
        else:
            ebitda[c] = base + fin[c] + dep[c] - (other[c] or 0.0)

    # Arithmetic cross-check on every column: PBT - tax should equal PAT.
    for c, label in zip(COLUMNS, ("this quarter", "previous quarter", "year-ago quarter")):
        if pbt[c] is None or tax[c] is None or pat[c] is None:
            continue
        gap = abs(pbt[c] - tax[c] - pat[c])
        ok = gap <= max(0.01 * abs(pat[c]), 0.5)
        if not ok:
            checks.append({"name": f"pbt_tax_pat_{c}", "ok": False,
                           "note": f"PBT − tax differs from PAT by ₹{gap:,.1f} cr for {label} "
                                   "(share of associates/JVs or a misread figure)."})
    if not checks:
        checks.append({"name": "pbt_tax_pat", "ok": True, "note": "PBT − tax = PAT in all three quarters."})
    if revenue["cur"] is None or pat["cur"] is None:
        checks.append({"name": "missing", "ok": False, "note": "Revenue or PAT could not be read."})

    return {
        "type": "results",
        "basis": extracted.get("basis") or "Reported",
        "unit": "₹ cr",
        "period": period,
        "metrics": {"revenue": _metric(revenue), "ebitda": _metric(ebitda),
                    "pbt": _metric(pbt), "pat": _metric(pat)},
        "margins": {"ebitda": _margin(ebitda, revenue), "pat": _margin(pat, revenue)},
        "ebitda_definition": EBITDA_DEFINITION if ebitda["cur"] is not None
        else "EBITDA is not shown: it is not meaningful for lenders or was not derivable from this filing.",
        "checks": checks,
        "page": page,
    }


PL_MARKERS = re.compile(r"profit\s*(/\s*\(?loss\)?\s*)?before\s+(exceptional\s+items\s+and\s+)?tax", re.I)
INCOME_MARKERS = re.compile(r"revenue from operations|total income|interest earned", re.I)


def find_results_page(pdf_path: str) -> tuple[int, str, str] | None:
    """Locate the quarterly P&L table: (1-based page, page text, basis).

    Prefers the consolidated statement; falls back to standalone. Balance-sheet and
    cash-flow pages are excluded by requiring both an income line and a PBT line.
    """
    best: tuple[int, int, str, str] | None = None
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            text = page.get_text()
            low = text.lower()
            if not (PL_MARKERS.search(low) and INCOME_MARKERS.search(low)):
                continue
            if "quarter ended" not in low and "three months ended" not in low:
                continue
            head = low[:1500]
            consolidated = "consolidated" in head and "standalone financial results" not in head
            rank = (2 if consolidated else 1) * 1000 - i  # consolidated first, then earliest page
            if best is None or rank > best[0]:
                best = (rank, i + 1, text, "Consolidated" if consolidated else "Standalone")
    return None if best is None else (best[1], best[2], best[3])
