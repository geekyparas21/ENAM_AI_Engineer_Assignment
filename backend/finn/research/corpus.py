"""The primary-source corpus for one company: its recent concall transcripts and latest
annual report, as per-page text, plus lexical retrieval over those pages.

Retrieval is BM25, not embeddings. Reasons: questions about filings are keyword-heavy
("capex", "attrition", "net debt"), BM25 needs no model, no download and no API quota,
and it runs comfortably inside a free-tier instance. A page is the unit of retrieval,
because a page is also the unit of citation.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Callable

from .. import documents
from ..config import DATA_DIR
from ..results import infer_period

RESEARCH_DIR = DATA_DIR / "research"
MAX_TRANSCRIPTS = 5
MAX_ANNUAL_REPORT_PAGES = 600
MIN_PAGE_CHARS = 200
BSE_REFERER = "https://www.bseindia.com/"
MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}

Progress = Callable[[str, int, int], None]


def call_quarter(period: str | None) -> str | None:
    """A call held in 'Nov 2026' discusses the quarter that ended before it: 'Q2 FY27'."""
    m = re.fullmatch(r"([A-Z][a-z]{2}) (20\d{2})", period or "")
    if not m or m.group(1) not in MONTH_NUM:
        return None
    return infer_period(f"{m.group(2)}-{MONTH_NUM[m.group(1)]:02d}-15")


def select_documents(company: dict) -> list[dict]:
    """Latest transcripts (newest first) and the latest annual report."""
    docs: list[dict] = []
    calls = [c for c in company["documents"]["concalls"] if c.get("transcript")][:MAX_TRANSCRIPTS]
    for i, call in enumerate(calls):
        quarter = call_quarter(call["period"])
        docs.append({
            "id": f"T{i + 1}", "kind": "transcript", "period": call["period"], "quarter": quarter,
            "label": f"{quarter} concall ({call['period']})" if quarter else f"Concall ({call['period']})",
            "short": f"{quarter} call" if quarter else f"{call['period']} call",
            "url": call["transcript"],
        })
    reports = company["documents"]["annual_reports"]
    if reports:
        report = reports[0]
        year = report.get("year")
        docs.append({
            "id": "AR1", "kind": "annual_report", "period": str(year) if year else None, "quarter": None,
            "label": f"Annual report FY{year % 100:02d}" if year else "Annual report",
            "short": f"AR FY{year % 100:02d}" if year else "Annual report",
            "url": report["url"],
        })
    return docs


def build(symbol: str, company: dict, progress: Progress | None = None) -> dict:
    """Download and read every selected document; return {'docs': [...], 'pages': [...]}.

    A document that cannot be fetched or has no text layer is recorded with its problem
    and skipped: research proceeds on what is readable and says what is missing.
    """
    docs = select_documents(company)
    pages: list[dict] = []
    for n, doc in enumerate(docs):
        if progress:
            progress(f"Reading {doc['label']}", n, len(docs))
        try:
            texts = documents.pages(doc["url"], referer=BSE_REFERER)
        except documents.DocumentError as exc:
            doc["pages"], doc["problem"] = 0, f"Could not be read: {exc}"
            continue
        if not documents.has_text_layer(texts):
            doc["pages"], doc["problem"] = len(texts), "Image-only scan; no text to read."
            continue
        doc["pages"] = len(texts)
        limit = MAX_ANNUAL_REPORT_PAGES if doc["kind"] == "annual_report" else len(texts)
        for i, text in enumerate(texts[:limit]):
            clean = text.strip()
            if len(clean) >= MIN_PAGE_CHARS:
                pages.append({"doc": doc["id"], "page": i + 1, "text": clean})
    if progress:
        progress("Documents read", len(docs), len(docs))
    return {"symbol": symbol.upper(), "docs": docs, "pages": pages}


def path_for(symbol: str) -> Path:
    return RESEARCH_DIR / symbol.upper()


def save(corpus: dict) -> None:
    folder = path_for(corpus["symbol"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chunks.json").write_text(json.dumps(corpus, ensure_ascii=False), encoding="utf-8")


def load(symbol: str) -> dict | None:
    path = path_for(symbol) / "chunks.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def page_text(corpus: dict, doc_id: str, page: int) -> str | None:
    for p in corpus["pages"]:
        if p["doc"] == doc_id and p["page"] == page:
            return p["text"]
    return None


def doc_pages(corpus: dict, doc_id: str) -> list[dict]:
    return [p for p in corpus["pages"] if p["doc"] == doc_id]


# --- BM25 --------------------------------------------------------------------------------

STOPWORDS = frozenset("""a an and are as at be been but by for from has have in is it its of on or that the
their this to was were will with we our you your they them what which who how why when where do does did
can could would should may might about into over than then there these those so if not no yes also per
company companys limited ltd please thank thanks question answer sir madam""".split())
TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in TOKEN.findall(text.lower()) if t not in STOPWORDS and len(t) > 1]


class Index:
    """Okapi BM25 over pages. Built once per company and kept in memory."""

    def __init__(self, pages: list[dict], k1: float = 1.5, b: float = 0.75) -> None:
        self.pages = pages
        self.k1, self.b = k1, b
        self.counts = [Counter(tokenize(p["text"])) for p in pages]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df: Counter = Counter()
        for c in self.counts:
            df.update(c.keys())
        n = len(pages)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 8, docs: set[str] | None = None, kinds_first: bool = False) -> list[dict]:
        terms = tokenize(query)
        scored: list[tuple[float, int]] = []
        for i, counts in enumerate(self.counts):
            if docs is not None and self.pages[i]["doc"] not in docs:
                continue
            score = 0.0
            for t in terms:
                f = counts.get(t)
                if not f:
                    continue
                norm = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1.0))
                score += self.idf.get(t, 0.0) * f * (self.k1 + 1) / norm
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [{**self.pages[i], "score": round(s, 3)} for s, i in scored[:k]]


_INDEX_CACHE: dict[str, tuple[int, Index]] = {}


def index_for(corpus: dict) -> Index:
    key = corpus["symbol"]
    cached = _INDEX_CACHE.get(key)
    if cached and cached[0] == len(corpus["pages"]):
        return cached[1]
    index = Index(corpus["pages"])
    _INDEX_CACHE[key] = (len(corpus["pages"]), index)
    return index
