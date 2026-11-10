"""Results card maths. The model only reads line items off the page; every derived
number here (EBITDA, margins, QoQ, YoY) is computed in code and cross-checked.

EBITDA definition used throughout (operating view):
    EBITDA = PBT (before exceptional items) + finance costs + depreciation & amortisation
             - other income
Banks and other lenders have no meaningful EBITDA (interest is their raw material),
so when finance costs or depreciation are absent the EBITDA rows are left empty.

Two legs feed a card:
  1. the results filing itself (PDF page -> line items -> maths here), the primary path;
  2. screener.in's standardised quarterly table, used to cross-check leg 1 and as a
     clearly labelled fallback when the filing cannot be read (image scan, broken file).
"""
from __future__ import annotations

import re

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

    def diff(a: float | None, b: float | None) -> float | None:
        return round(a - b, 1) if a is not None and b is not None else None

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
        "source": "filing",
        "source_note": f"Read from p.{page} of the results filing." if page else "Read from the results filing.",
    }


# --- locating the P&L page ----------------------------------------------------------------

# Scanned filings carry OCR noise ("fmance costs", "exceptionaJ items"), so a page is
# recognised as a P&L statement by how many of these line items it contains, not by
# any single exact phrase.
PL_KEYWORDS = (
    "revenue from operations", "total income", "other income", "finance cost", "depreciation",
    "tax expense", "profit before", "earnings per", "total expenses", "interest earned",
    "employee benefit", "profit for the",
)
MIN_KEYWORDS = 5
QUARTER_MARKERS = ("quarter ended", "three months ended", "quarter and", "3 months ended")
TITLE = re.compile(r"(consolidated|standalone)", re.I)


def pl_score(text: str) -> int:
    low = " ".join(text.lower().split())
    return sum(1 for k in PL_KEYWORDS if k in low)


def page_basis(text: str) -> str | None:
    """Consolidated or Standalone, from the statement title near the top of the page."""
    m = TITLE.search(" ".join(text.split())[:1200])
    return m.group(1).capitalize() if m else None


def find_results_page(page_texts: list[str]) -> tuple[int, str, str | None] | None:
    """Locate the quarterly P&L table: (1-based page, page text, basis).

    Consolidated is preferred, then a page whose basis is unclear, then standalone;
    within a group the earliest page wins (later ones are usually segment notes).
    """
    order = {"Consolidated": 0, None: 1, "Standalone": 2}
    best: tuple[int, int] | None = None
    for i, text in enumerate(page_texts):
        low = " ".join(text.lower().split())
        if pl_score(text) < MIN_KEYWORDS or not any(q in low for q in QUARTER_MARKERS):
            continue
        key = (order[page_basis(text)], i)
        if best is None or key < best:
            best = key
    if best is None:
        return None
    text = page_texts[best[1]]
    return best[1] + 1, text, page_basis(text)


# --- periods --------------------------------------------------------------------------------

QUARTER_END = {1: "Jun", 2: "Sep", 3: "Dec", 4: "Mar"}
MONTH_ORDER = ["Mar", "Jun", "Sep", "Dec"]


def period_to_column(period: str | None) -> str | None:
    """'Q2 FY27' -> 'Sep 2026' (screener labels quarters by their end month)."""
    m = re.fullmatch(r"Q([1-4]) FY(\d{2})", period or "")
    if not m:
        return None
    quarter, fy = int(m.group(1)), 2000 + int(m.group(2))
    year = fy if quarter == 4 else fy - 1
    return f"{QUARTER_END[quarter]} {year}"


def infer_period(ts: str) -> str:
    """Latest completed quarter before a filing date, for subjects that do not name one."""
    year, month = int(ts[:4]), int(ts[5:7])
    if month <= 3:
        return f"Q3 FY{year % 100:02d}"
    if month <= 6:
        return f"Q4 FY{year % 100:02d}"
    if month <= 9:
        return f"Q1 FY{(year + 1) % 100:02d}"
    return f"Q2 FY{(year + 1) % 100:02d}"


def _shift(column: str, quarters: int) -> str:
    month, year = column.split()
    idx = MONTH_ORDER.index(month) + int(year) * 4 + quarters
    return f"{MONTH_ORDER[idx % 4]} {idx // 4}"


# --- screener.in leg: cross-check, and fallback when the filing cannot be read ------------

def _screener_columns(table: dict, period: str | None) -> dict[str, int | None] | None:
    column = period_to_column(period)
    if column is None or column not in table["columns"]:
        return None
    index = {name: i for i, name in enumerate(table["columns"])}
    return {"cur": index[column], "prev": index.get(_shift(column, -1)), "yoy": index.get(_shift(column, -4))}


def _screener_row(table: dict, names: tuple[str, ...], cols: dict[str, int | None]) -> dict[str, float | None]:
    row = next((table["rows"][n] for n in names if n in table["rows"]), None)
    return {c: (row[i] if row is not None and i is not None else None) for c, i in cols.items()}


def card_from_screener(company: dict, period: str | None, reason: str) -> dict | None:
    """Results card from screener.in's standardised quarterly table (already Rs crore).

    Used only when the filing itself was not read; `reason` says why, and the card
    carries it so the reader knows these figures were not parsed from the PDF.
    """
    table = company["quarters"]
    cols = _screener_columns(table, period)
    if cols is None:
        return None
    revenue = _screener_row(table, ("Sales", "Revenue"), cols)
    pbt = _screener_row(table, ("Profit before tax",), cols)
    pat = _screener_row(table, ("Net Profit",), cols)
    lender = "Financing Profit" in table["rows"]
    none: dict[str, float | None] = {"cur": None, "prev": None, "yoy": None}
    ebitda = none if lender else _screener_row(table, ("Operating Profit",), cols)
    if revenue["cur"] is None or pat["cur"] is None:
        return None
    return {
        "type": "results",
        "basis": company["basis"],
        "unit": "₹ cr",
        "period": period,
        "metrics": {"revenue": _metric(revenue), "ebitda": _metric(ebitda),
                    "pbt": _metric(pbt), "pat": _metric(pat)},
        "margins": {"ebitda": _margin(ebitda, revenue), "pat": _margin(pat, revenue)},
        "ebitda_definition": "EBITDA is not shown: it is not meaningful for lenders." if lender
        else "EBITDA = operating profit before other income, depreciation and interest.",
        "checks": [],
        "page": None,
        "source": "screener",
        "source_note": f"{reason} Figures are from screener.in's standardised quarterly table, "
                       "rounded to ₹ crore.",
    }


def cross_check(card: dict, company: dict, period: str | None, tolerance_pct: float = 1.5) -> list[dict]:
    """Compare filing-derived revenue and PAT with screener's table for the same quarter."""
    cols = _screener_columns(company["quarters"], period)
    if cols is None:
        return [{"name": "screener", "ok": True, "note": "Not yet on screener.in; no independent cross-check."}]
    if card["basis"] != company["basis"]:
        return [{"name": "screener", "ok": True,
                 "note": f"Filing figures are {card['basis'].lower()}; screener shows "
                         f"{company['basis'].lower()}, so not compared."}]
    checks = []
    quarter_label = {"cur": "this quarter", "prev": "the previous quarter", "yoy": "the year-ago quarter"}
    lender = "Financing Profit" in company["quarters"]["rows"]
    # Revenue, PBT and PAT are reported the same way everywhere, so they must reconcile.
    # EBITDA depends on what counts as other income, so it gets a wider band and only a warning.
    specs = [("revenue", ("Sales", "Revenue"), "Revenue", tolerance_pct),
             ("pbt", ("Profit before tax",), "PBT", tolerance_pct),
             ("pat", ("Net Profit",), "PAT", tolerance_pct)]
    if not lender:
        specs.append(("ebitda", ("Operating Profit",), "EBITDA", 5.0))
    for key, names, label, tol in specs:
        theirs_row = _screener_row(company["quarters"], names, cols)
        ours_row = card["metrics"].get(key) or {}
        worst: tuple[str, float, float] | None = None
        compared = 0
        for col in COLUMNS:
            ours, theirs = ours_row.get(col), theirs_row[col]
            if ours is None or theirs is None:
                continue
            compared += 1
            # screener rounds to whole crores, so allow that rounding on small numbers
            if abs(ours - theirs) > max(abs(theirs) * tol / 100.0, 1.0) and worst is None:
                worst = (col, ours, theirs)
        if compared == 0:
            continue
        if worst is None:
            note = f"{label} matches screener.in in {compared} of {compared} quarters compared."
        else:
            col, ours, theirs = worst
            note = (f"{label} for {quarter_label[col]} reads ₹{ours:,.0f} cr in the filing but "
                    f"screener.in shows ₹{theirs:,.0f} cr.")
            if key == "ebitda":
                note += " The two may treat other income differently."
        checks.append({"name": f"screener_{key}", "ok": worst is None, "note": note})
    return checks


CORE_CHECKS = ("screener_revenue", "screener_pbt", "screener_pat")


def reconciles(checks: list[dict]) -> bool:
    """True unless a core figure (revenue, PBT, PAT) disagrees with screener.in."""
    return all(c["ok"] for c in checks if c["name"] in CORE_CHECKS)


def summary_line(card: dict) -> str:
    """The one-line takeaway on a results card. Composed from the numbers, in code."""
    rev, pat = card["metrics"]["revenue"]["yoy_pct"], card["metrics"]["pat"]["yoy_pct"]
    period = card.get("period") or "Quarter"

    def mag(v: float) -> str:
        return f"{abs(v):.1f}%"

    if rev is None or pat is None:
        cur = card["metrics"]["pat"]["cur"]
        if cur is None:
            return f"{period} results"
        return f"{period}: PAT ₹{cur:,.0f} cr; no clean year-ago comparison."
    if rev >= 0 > pat:
        head = f"Revenue up {mag(rev)} YoY but PAT down {mag(pat)}"
    elif pat >= 0 > rev:
        head = f"PAT up {mag(pat)} YoY despite revenue down {mag(rev)}"
    elif rev < 0 and pat < 0:
        head = f"Revenue down {mag(rev)} and PAT down {mag(pat)} YoY"
    elif pat - rev > 5:
        head = f"PAT up {mag(pat)} YoY, ahead of revenue at +{mag(rev)}"
    elif rev - pat > 5:
        head = f"Revenue up {mag(rev)} YoY, PAT lagging at +{mag(pat)}"
    else:
        head = f"Revenue up {mag(rev)} and PAT up {mag(pat)} YoY"
    margin = card["margins"]["ebitda"]
    if margin["cur"] is not None and margin["yoy_pct"] is not None and abs(margin["yoy_pct"]) >= 0.5:
        verb = "expanded" if margin["yoy_pct"] > 0 else "compressed"
        head += f"; EBITDA margin {verb} {abs(margin['yoy_pct']):.1f}pp to {margin['cur']:.1f}%"
    return f"{period}: {head}."
