"""screener.in company page: standardised financial tables and document links.

One HTML page per company carries everything we need: quarterly and annual tables,
balance sheet, cash flow, ratios, and links to annual reports and concall transcripts.
The page is cached on disk; we fetch at most once per TTL and pause between requests.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..config import CACHE_DIR, USER_AGENT

BASE = "https://www.screener.in/company"
PAGE_DIR = CACHE_DIR / "screener"
TTL_SECONDS = 12 * 3600
PAUSE_SECONDS = 1.2
_last_request = 0.0


class ScreenerError(RuntimeError):
    """The company page could not be fetched or has no usable data."""


def _get(url: str) -> requests.Response:
    global _last_request
    wait = PAUSE_SECONDS - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.time()
    return requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, timeout=40)


def _cached(path: Path) -> str | None:
    if path.exists() and time.time() - path.stat().st_mtime < TTL_SECONDS:
        return path.read_text(encoding="utf-8")
    return None


def fetch_page(symbol: str, refresh: bool = False) -> tuple[str, str]:
    """Return (html, basis). Consolidated first; standalone when a company has no
    consolidated numbers (single-entity companies)."""
    symbol = symbol.upper().strip()
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", symbol):
        raise ScreenerError(f"Not a valid NSE symbol: {symbol!r}")
    PAGE_DIR.mkdir(parents=True, exist_ok=True)
    last_error = "no data"
    for basis, suffix in (("Consolidated", "consolidated/"), ("Standalone", "")):
        path = PAGE_DIR / f"{symbol}.{basis.lower()}.html"
        html = None if refresh else _cached(path)
        if html is None:
            try:
                resp = _get(f"{BASE}/{symbol}/{suffix}")
            except requests.RequestException as exc:
                stale = path.read_text(encoding="utf-8") if path.exists() else None
                if stale and _has_quarters(stale):
                    return stale, basis  # source is down: serve what we have
                last_error = str(exc)
                continue
            if resp.status_code == 404:
                raise ScreenerError(f"{symbol} is not on screener.in")
            if resp.status_code != 200:
                last_error = f"HTTP {resp.status_code}"
                continue
            html = resp.text
            path.write_text(html, encoding="utf-8")
        if _has_quarters(html):
            return html, basis
    raise ScreenerError(f"No financial tables for {symbol} ({last_error})")


def _has_quarters(html: str) -> bool:
    table = parse_table(BeautifulSoup(html, "lxml"), "quarters")
    return bool(table["columns"]) and any(v is not None for row in table["rows"].values() for v in row)


def _number(text: str) -> float | None:
    text = text.replace(",", "").replace("%", "").replace("₹", "").strip()
    if not text or text in {"-", "--"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _label(text: str) -> str:
    return re.sub(r"\s*\+\s*$", "", " ".join(text.split())).strip()


def parse_table(soup: BeautifulSoup, section_id: str) -> dict:
    """{'columns': ['Sep 2025', ...], 'rows': {'Sales': [..], 'Net Profit': [..]}}"""
    section = soup.find("section", id=section_id)
    table = section.find("table") if section else None
    if table is None or table.find("thead") is None:
        return {"columns": [], "rows": {}}
    columns = [th.get_text(strip=True) for th in table.find("thead").find_all("th")][1:]
    rows: dict[str, list[float | None]] = {}
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = _label(cells[0].get_text(" ", strip=True))
        if label and label != "Raw PDF":
            rows[label] = [_number(td.get_text(strip=True)) for td in cells[1:]]
    return {"columns": columns, "rows": rows}


def parse_documents(soup: BeautifulSoup) -> dict:
    """Annual reports and concall links, newest first, as listed by screener."""
    section = soup.find("section", id="documents")
    out: dict[str, list[dict]] = {"annual_reports": [], "concalls": []}
    if section is None:
        return out
    box = section.find("div", class_="annual-reports")
    for li in (box.find_all("li") if box else []):
        a = li.find("a")
        if not a or not a.get("href"):
            continue
        title = " ".join(a.get_text(" ", strip=True).split())
        year = re.search(r"(20\d{2})", title)
        out["annual_reports"].append({
            "title": re.sub(r"\s*from (bse|nse)$", "", title, flags=re.I),
            "year": int(year.group(1)) if year else None,
            "url": a["href"],
        })
    box = section.find("div", class_="concalls")
    for li in (box.find_all("li") if box else []):
        text = " ".join(li.get_text(" ", strip=True).split())
        when = re.match(r"([A-Z][a-z]{2} 20\d{2})", text)
        links = {a.get_text(strip=True).lower(): a.get("href") for a in li.find_all("a") if a.get("href")}
        out["concalls"].append({
            "period": when.group(1) if when else None,
            "transcript": links.get("transcript"),
            "ppt": links.get("ppt"),
            "recording": links.get("rec"),
        })
    return out


def company(symbol: str, refresh: bool = False) -> dict:
    """Everything FINN uses from the page, parsed."""
    html, basis = fetch_page(symbol, refresh)
    soup = BeautifulSoup(html, "lxml")
    name = soup.find("h1")
    about = soup.select_one("div.about p")
    ratios = {}
    for li in soup.select("ul#top-ratios li"):
        key = li.find("span", class_="name")
        value = li.find("span", class_="number")
        if key and value:
            ratios[" ".join(key.get_text(" ", strip=True).split())] = _number(value.get_text(strip=True))
    return {
        "symbol": symbol.upper(),
        "name": name.get_text(strip=True) if name else symbol.upper(),
        "basis": basis,
        "unit": "₹ cr",
        "about": " ".join(about.get_text(" ", strip=True).split()) if about else None,
        "ratios": ratios,
        "quarters": parse_table(soup, "quarters"),
        "profit_loss": parse_table(soup, "profit-loss"),
        "balance_sheet": parse_table(soup, "balance-sheet"),
        "cash_flow": parse_table(soup, "cash-flow"),
        "ratio_table": parse_table(soup, "ratios"),
        "documents": parse_documents(soup),
        "url": f"{BASE}/{symbol.upper()}/{'consolidated/' if basis == 'Consolidated' else ''}",
    }
