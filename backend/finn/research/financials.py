"""The numbers side of research, computed in code from screener.in's standardised tables.

Two outputs:
  view(company)    the Snapshot / Trajectory / Cash quality / Balance sheet tabs
  actuals(company) a flat table of delivered figures, keyed like "FY26.revenue_growth" or
                   "Q2FY27.ebitda_margin", that the Promise Tracker judges guidance against.
                   The model never writes a delivered number; it can only point at a key here.
"""
from __future__ import annotations

MONTHS = {"Mar": 3, "Jun": 6, "Sep": 9, "Dec": 12}


def fiscal_year(column: str) -> str | None:
    """'Mar 2026' -> 'FY26'. Companies with a December year-end get 'CY25'."""
    parts = column.split()
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    month, year = parts[0], int(parts[1])
    if month == "Mar":
        return f"FY{year % 100:02d}"
    if month == "Dec":
        return f"CY{year % 100:02d}"
    return f"FY{year % 100:02d}"


def fiscal_quarter(column: str) -> str | None:
    """'Sep 2026' -> 'Q2 FY27' (April-March fiscal year)."""
    parts = column.split()
    if len(parts) != 2 or parts[0] not in MONTHS or not parts[1].isdigit():
        return None
    month, year = MONTHS[parts[0]], int(parts[1])
    quarter = {6: 1, 9: 2, 12: 3, 3: 4}[month]
    fy = year if month == 3 else year + 1
    return f"Q{quarter} FY{fy % 100:02d}"


def _row(table: dict, *names: str) -> list[float | None]:
    for name in names:
        if name in table["rows"]:
            return table["rows"][name]
    # screener appends explanatory text to some labels ("CFO/EBITDA Share of ...")
    for label, values in table["rows"].items():
        if any(label.startswith(n) for n in names):
            return values
    return [None] * len(table["columns"])


def _growth(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base <= 0:
        return None
    return round((cur / base - 1.0) * 100.0, 1)


def _ratio(num: float | None, den: float | None, scale: float = 100.0, digits: int = 1) -> float | None:
    if num is None or not den:
        return None
    return round(scale * num / den, digits)


def _annual_columns(table: dict) -> list[int]:
    """Indices of full-year columns (drops 'TTM' and half-year balance-sheet columns)."""
    cols = [i for i, c in enumerate(table["columns"]) if fiscal_year(c) and c.split()[0] in ("Mar", "Dec")]
    months = {table["columns"][i].split()[0] for i in cols}
    if months == {"Mar", "Dec"}:  # a March year-end company never has Dec annual columns
        cols = [i for i in cols if table["columns"][i].startswith("Mar")]
    return cols


def is_lender(company: dict) -> bool:
    return "Financing Profit" in company["quarters"]["rows"]


def annual_series(company: dict, keep: int = 6) -> dict:
    pl = company["profit_loss"]
    idx = _annual_columns(pl)[-keep:]
    revenue, pat = _row(pl, "Sales", "Revenue"), _row(pl, "Net Profit")
    op = [None] * len(pl["columns"]) if is_lender(company) else _row(pl, "Operating Profit")
    eps = _row(pl, "EPS in Rs")
    out = {"years": [], "revenue": [], "revenue_growth": [], "ebitda": [], "ebitda_margin": [], "pat": [],
           "pat_growth": [], "pat_margin": [], "eps": []}
    for i in idx:
        prev = i - 1 if i - 1 >= 0 and fiscal_year(pl["columns"][i - 1]) else None
        out["years"].append(fiscal_year(pl["columns"][i]))
        out["revenue"].append(revenue[i])
        out["revenue_growth"].append(_growth(revenue[i], revenue[prev]) if prev is not None else None)
        out["ebitda"].append(op[i])
        out["ebitda_margin"].append(_ratio(op[i], revenue[i]))
        out["pat"].append(pat[i])
        out["pat_growth"].append(_growth(pat[i], pat[prev]) if prev is not None else None)
        out["pat_margin"].append(_ratio(pat[i], revenue[i]))
        out["eps"].append(eps[i])
    if "TTM" in pl["columns"]:
        t = pl["columns"].index("TTM")
        out["ttm"] = {"revenue": revenue[t], "ebitda": op[t], "ebitda_margin": _ratio(op[t], revenue[t]),
                      "pat": pat[t], "pat_margin": _ratio(pat[t], revenue[t])}
    return out


def quarterly_series(company: dict, keep: int = 9) -> dict:
    q = company["quarters"]
    n = len(q["columns"])
    revenue, pat = _row(q, "Sales", "Revenue"), _row(q, "Net Profit")
    op = [None] * n if is_lender(company) else _row(q, "Operating Profit")
    out = {"periods": [], "columns": [], "revenue": [], "revenue_yoy": [], "revenue_qoq": [], "ebitda": [],
           "ebitda_margin": [], "pat": [], "pat_yoy": []}
    for i in range(max(0, n - keep), n):
        out["periods"].append(fiscal_quarter(q["columns"][i]) or q["columns"][i])
        out["columns"].append(q["columns"][i])
        out["revenue"].append(revenue[i])
        out["revenue_yoy"].append(_growth(revenue[i], revenue[i - 4]) if i >= 4 else None)
        out["revenue_qoq"].append(_growth(revenue[i], revenue[i - 1]) if i >= 1 else None)
        out["ebitda"].append(op[i])
        out["ebitda_margin"].append(_ratio(op[i], revenue[i]))
        out["pat"].append(pat[i])
        out["pat_yoy"].append(_growth(pat[i], pat[i - 4]) if i >= 4 else None)
    return out


def year_to_date(company: dict) -> dict | None:
    """The current fiscal year so far, versus the same quarters a year earlier.

    Lets an open full-year target be judged as ahead or behind before the year ends.
    """
    q = company["quarters"]
    labels = [fiscal_quarter(c) for c in q["columns"]]
    if not labels or labels[-1] is None:
        return None
    fy = labels[-1].split()[1]
    cur = [i for i, lab in enumerate(labels) if lab and lab.endswith(fy)]
    if not cur or min(cur) < 4 or len(cur) == 4:
        return None  # a completed year is covered by the annual figures
    revenue, pat = _row(q, "Sales", "Revenue"), _row(q, "Net Profit")
    op = [None] * len(labels) if is_lender(company) else _row(q, "Operating Profit")

    def total(row: list[float | None], idx: list[int]) -> float | None:
        vals = [row[i] for i in idx]
        return None if any(v is None for v in vals) else float(sum(vals))

    prior = [i - 4 for i in cur]
    rev, rev_prior = total(revenue, cur), total(revenue, prior)
    return {
        "fy": fy, "quarters": len(cur),
        "label": f"{'H1' if len(cur) == 2 else str(len(cur)) + 'Q' if len(cur) != 3 else '9M'} {fy}",
        "revenue": rev, "revenue_growth": _growth(rev, rev_prior),
        "ebitda_margin": _ratio(total(op, cur), rev),
        "pat": total(pat, cur), "pat_growth": _growth(total(pat, cur), total(pat, prior)),
    }


def cash_series(company: dict, keep: int = 5) -> dict:
    cf, pl = company["cash_flow"], company["profit_loss"]
    idx = _annual_columns(cf)[-keep:]
    cfo, fcf, cfo_ebitda = _row(cf, "Cash from Operating Activity"), _row(cf, "Free Cash Flow"), _row(cf, "CFO/EBITDA", "CFO/OP")
    pat_by_year = {fiscal_year(c): v for c, v in zip(pl["columns"], _row(pl, "Net Profit")) if fiscal_year(c)}
    out = {"years": [], "cfo": [], "pat": [], "conversion": [], "fcf": [], "cfo_ebitda": []}
    for i in idx:
        year = fiscal_year(cf["columns"][i])
        pat = pat_by_year.get(year)
        out["years"].append(year)
        out["cfo"].append(cfo[i])
        out["pat"].append(pat)
        out["conversion"].append(_ratio(cfo[i], pat, digits=0) if pat and pat > 0 else None)
        out["fcf"].append(fcf[i])
        out["cfo_ebitda"].append(cfo_ebitda[i])
    return out


def balance_series(company: dict, keep: int = 5) -> dict:
    bs, ratios = company["balance_sheet"], company["ratio_table"]
    n = len(bs["columns"])
    idx = list(range(max(0, n - keep), n))  # includes the latest half-year column when present
    equity_cap, reserves = _row(bs, "Equity Capital"), _row(bs, "Reserves")
    borrowings = _row(bs, "Borrowings", "Borrowing")
    out = {"periods": [], "borrowings": [], "equity": [], "debt_equity": [], "total_assets": []}
    for i in idx:
        equity = None if equity_cap[i] is None or reserves[i] is None else equity_cap[i] + reserves[i]
        col = bs["columns"][i]
        out["periods"].append(fiscal_year(col) if col.split()[0] in ("Mar", "Dec") else col.replace(" 20", " '"))
        out["borrowings"].append(borrowings[i])
        out["equity"].append(equity)
        out["debt_equity"].append(_ratio(borrowings[i], equity, scale=1.0, digits=2))
        out["total_assets"].append(_row(bs, "Total Assets")[i])
    ridx = _annual_columns(ratios)[-keep:]
    out["working_capital"] = {
        "years": [fiscal_year(ratios["columns"][i]) for i in ridx],
        "debtor_days": [_row(ratios, "Debtor Days")[i] for i in ridx],
        "inventory_days": [_row(ratios, "Inventory Days")[i] for i in ridx],
        "payable_days": [_row(ratios, "Days Payable")[i] for i in ridx],
        "cash_conversion_cycle": [_row(ratios, "Cash Conversion Cycle")[i] for i in ridx],
        "roce": [_row(ratios, "ROCE %")[i] for i in ridx],
    }
    return out


def _last(values: list, n: int = 1):
    vals = [v for v in values if v is not None]
    return vals[-n] if len(vals) >= n else None


def observations(annual: dict, cash: dict, balance: dict, ytd: dict | None) -> list[str]:
    """Plain statements of direction, generated from the series. No model involved."""
    out: list[str] = []
    years, growth = annual["years"], annual["revenue_growth"]
    pairs = [(y, g) for y, g in zip(years, growth) if g is not None]
    if len(pairs) >= 2:
        (y0, g0), (y1, g1) = pairs[-2], pairs[-1]
        verb = "accelerated" if g1 > g0 + 1 else "slowed" if g1 < g0 - 1 else "held"
        out.append(f"Revenue growth {verb} from {g0:.1f}% in {y0} to {g1:.1f}% in {y1}.")
    margins = [(y, m) for y, m in zip(years, annual["ebitda_margin"]) if m is not None]
    if len(margins) >= 3:
        (y0, m0), (y1, m1) = margins[-3], margins[-1]
        delta = m1 - m0
        if abs(delta) >= 0.5:
            out.append(f"EBITDA margin {'expanded' if delta > 0 else 'compressed'} {abs(delta):.1f}pp "
                       f"between {y0} ({m0:.1f}%) and {y1} ({m1:.1f}%).")
    if ytd and ytd.get("revenue_growth") is not None:
        line = f"{ytd['label']}: revenue {ytd['revenue_growth']:+.1f}% YoY"
        if ytd.get("pat_growth") is not None:
            line += f", PAT {ytd['pat_growth']:+.1f}%"
        if ytd.get("ebitda_margin") is not None:
            line += f", EBITDA margin {ytd['ebitda_margin']:.1f}%"
        out.append(line + ".")
    conv = [(y, c) for y, c in zip(cash["years"], cash["conversion"]) if c is not None]
    if conv:
        above = sum(1 for _, c in conv if c >= 100)
        out.append(f"Operating cash flow exceeded PAT in {above} of the last {len(conv)} years "
                   f"(latest {conv[-1][0]}: {conv[-1][1]:.0f}% of PAT).")
    de = [(p, d) for p, d in zip(balance["periods"], balance["debt_equity"]) if d is not None]
    if len(de) >= 2:
        (p0, d0), (p1, d1) = de[0], de[-1]
        if abs(d1 - d0) >= 0.05:
            out.append(f"Debt-to-equity {'rose' if d1 > d0 else 'fell'} from {d0:.2f} ({p0}) to {d1:.2f} ({p1}).")
        else:
            out.append(f"Debt-to-equity steady at {d1:.2f} ({p1}).")
    wc = balance["working_capital"]
    dd = [(y, d) for y, d in zip(wc["years"], wc["debtor_days"]) if d is not None]
    if len(dd) >= 2 and abs(dd[-1][1] - dd[0][1]) >= 5:
        out.append(f"Debtor days {'lengthened' if dd[-1][1] > dd[0][1] else 'shortened'} from "
                   f"{dd[0][1]:.0f} ({dd[0][0]}) to {dd[-1][1]:.0f} ({dd[-1][0]}).")
    return out


def view(company: dict) -> dict:
    annual, quarterly = annual_series(company), quarterly_series(company)
    cash, balance, ytd = cash_series(company), balance_series(company), year_to_date(company)
    ratios = company.get("ratios", {})
    ttm = annual.get("ttm", {})
    headline = [
        {"label": "Revenue (TTM)", "value": ttm.get("revenue"), "unit": "cr"},
        {"label": "EBITDA margin (TTM)", "value": ttm.get("ebitda_margin"), "unit": "%"},
        {"label": "PAT (TTM)", "value": ttm.get("pat"), "unit": "cr"},
        {"label": "ROCE", "value": ratios.get("ROCE"), "unit": "%"},
        {"label": "ROE", "value": ratios.get("ROE"), "unit": "%"},
        {"label": "Debt / equity", "value": _last(balance["debt_equity"]), "unit": "x"},
        {"label": "Market cap", "value": ratios.get("Market Cap"), "unit": "cr"},
        {"label": "P/E", "value": ratios.get("Stock P/E"), "unit": "x"},
    ]
    return {
        "basis": company["basis"], "unit": "₹ cr", "source": "screener.in standardised financials",
        "source_url": company["url"], "lender": is_lender(company),
        "headline": [h for h in headline if h["value"] is not None],
        "annual": annual, "quarterly": quarterly, "ytd": ytd, "cash": cash, "balance": balance,
        "observations": observations(annual, cash, balance, ytd),
    }


def actuals(company: dict) -> dict[str, dict]:
    """Delivered figures by key. Every value here is computed from reported numbers."""
    out: dict[str, dict] = {}

    def put(key: str, value: float | None, unit: str, label: str, partial: bool = False) -> None:
        if value is not None:
            out[key] = {"value": value, "unit": unit, "label": label, "partial": partial}

    annual, quarterly, cash, balance = annual_series(company, keep=5), quarterly_series(company), \
        cash_series(company), balance_series(company)
    for i, year in enumerate(annual["years"]):
        put(f"{year}.revenue", annual["revenue"][i], "cr", f"{year} revenue")
        put(f"{year}.revenue_growth", annual["revenue_growth"][i], "%", f"{year} revenue growth")
        put(f"{year}.ebitda_margin", annual["ebitda_margin"][i], "%", f"{year} EBITDA margin")
        put(f"{year}.pat", annual["pat"][i], "cr", f"{year} PAT")
        put(f"{year}.pat_growth", annual["pat_growth"][i], "%", f"{year} PAT growth")
        put(f"{year}.pat_margin", annual["pat_margin"][i], "%", f"{year} PAT margin")
    for i, period in enumerate(quarterly["periods"]):
        key = period.replace(" ", "")
        put(f"{key}.revenue", quarterly["revenue"][i], "cr", f"{period} revenue")
        put(f"{key}.revenue_yoy", quarterly["revenue_yoy"][i], "%", f"{period} revenue growth YoY")
        put(f"{key}.revenue_qoq", quarterly["revenue_qoq"][i], "%", f"{period} revenue growth QoQ")
        put(f"{key}.ebitda_margin", quarterly["ebitda_margin"][i], "%", f"{period} EBITDA margin")
        put(f"{key}.pat", quarterly["pat"][i], "cr", f"{period} PAT")
        put(f"{key}.pat_yoy", quarterly["pat_yoy"][i], "%", f"{period} PAT growth YoY")
    ytd = year_to_date(company)
    if ytd:
        key, label = f"{ytd['fy']}_YTD", f"{ytd['label']} ({ytd['quarters']} of 4 quarters)"
        put(f"{key}.revenue_growth", ytd["revenue_growth"], "%", f"{label} revenue growth YoY", partial=True)
        put(f"{key}.ebitda_margin", ytd["ebitda_margin"], "%", f"{label} EBITDA margin", partial=True)
        put(f"{key}.pat_growth", ytd["pat_growth"], "%", f"{label} PAT growth YoY", partial=True)
    for i, year in enumerate(cash["years"]):
        put(f"{year}.cfo", cash["cfo"][i], "cr", f"{year} operating cash flow")
        put(f"{year}.fcf", cash["fcf"][i], "cr", f"{year} free cash flow")
        put(f"{year}.cash_conversion", cash["conversion"][i], "%", f"{year} operating cash flow as % of PAT")
    for i, period in enumerate(balance["periods"]):
        key = period.replace(" ", "").replace("'", "")
        put(f"{key}.borrowings", balance["borrowings"][i], "cr", f"{period} borrowings")
        put(f"{key}.debt_equity", balance["debt_equity"][i], "x", f"{period} debt-to-equity")
    return out


def format_actual(entry: dict) -> str:
    value, unit = entry["value"], entry["unit"]
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "x":
        return f"{value:.2f}x"
    return f"₹{value:,.0f} cr"
