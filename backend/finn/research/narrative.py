"""Business snapshot and the bull and bear cases, written only from retrieved pages of the
company's own documents and from figures computed in code. Every point must cite a source
it was given; anything uncited is dropped before it is stored.
"""
from __future__ import annotations

import sqlite3

from .. import llm
from .corpus import index_for

PAGE_CHARS = 3200

# What to look for, and where. Annual report for the standing facts; latest calls for what changed.
QUERIES = [
    ("AR", "business overview what the company does products services offerings customers", 2),
    ("AR", "revenue by segment geography vertical mix percentage of revenue", 3),
    ("AR", "management discussion and analysis outlook opportunities growth drivers strategy", 2),
    ("AR", "risks concerns threats risk management customer concentration", 3),
    ("T", "outlook demand pipeline deal wins growth next year", 3),
    ("T", "margin pressure headwinds challenges delays pricing competition", 3),
]

SYSTEM = """You write a short research note on an Indian listed company for an investor, using ONLY the numbered
sources given. Sources S1, S2, ... are pages from the company's annual report and earnings-call transcripts.
Sources F1, F2, ... are facts computed from its reported financials.

Do not use anything you know about the company from elsewhere. If the sources do not say something, leave it out.
Every sentence or bullet must carry the ids of the sources that support it.

Write:
  business  2 to 3 sentences: what the company does, who it sells to, how it makes money.
  segments  how revenue splits by segment, vertical or geography, ONLY if the sources give the split.
            Use the percentages as printed. Empty list if not disclosed.
  bull      exactly 3 points for the case that the business does well from here.
  bear      exactly 3 points for the case that it disappoints.

Bull and bear points: one sentence each, at most 30 words, specific, with a number where the sources give one.
Prefer points where management's words and the computed figures agree (bull) or diverge (bear).
No filler, no adjectives such as robust, strong, significant.

Reply with JSON only:
{"business": {"text": "...", "cites": ["S1"]},
 "segments": [{"name": "...", "share": "55%" or null, "note": "one short clause or null", "cites": ["S2"]}],
 "bull": [{"point": "...", "cites": ["S3", "F1"]}],
 "bear": [{"point": "...", "cites": ["S5", "F2"]}]}"""


def gather_sources(corpus: dict) -> list[dict]:
    """Pick the pages the note is allowed to draw on, deduplicated, in a stable order."""
    index = index_for(corpus)
    transcripts = {d["id"] for d in corpus["docs"] if d["kind"] == "transcript"}
    reports = {d["id"] for d in corpus["docs"] if d["kind"] == "annual_report"}
    latest_calls = set(sorted(transcripts, key=lambda i: int(i[1:]))[:2])  # T1, T2 = two most recent
    seen: set[tuple[str, int]] = set()
    picked: list[dict] = []
    for where, query, k in QUERIES:
        docs = reports if where == "AR" else latest_calls
        if not docs:
            docs = transcripts or reports
        for hit in index.search(query, k=k + 2, docs=docs):
            key = (hit["doc"], hit["page"])
            if key in seen:
                continue
            seen.add(key)
            picked.append(hit)
            if sum(1 for p in picked if (p["doc"], p["page"]) in seen) and len([1 for p in picked]) >= 0:
                pass
            k -= 1
            if k <= 0:
                break
    return picked


def _cites(raw, valid: dict[str, dict]) -> list[dict]:
    out, seen = [], set()
    for c in raw if isinstance(raw, list) else []:
        key = str(c).strip().strip("[]")
        if key in valid and key not in seen:
            seen.add(key)
            out.append(valid[key])
    return out


def build(conn: sqlite3.Connection, corpus: dict, facts: list[str], name: str) -> dict:
    doc_by_id = {d["id"]: d for d in corpus["docs"]}
    pages = gather_sources(corpus)
    valid: dict[str, dict] = {}
    blocks = []
    for i, p in enumerate(pages):
        sid, doc = f"S{i + 1}", doc_by_id[p["doc"]]
        valid[sid] = {"id": sid, "kind": "page", "doc": doc["id"], "label": f"{doc['short']} p.{p['page']}",
                      "page": p["page"], "url": f"{doc['url']}#page={p['page']}"}
        blocks.append(f"[{sid}] {doc['label']}, page {p['page']}\n{p['text'][:PAGE_CHARS]}")
    for i, fact in enumerate(facts):
        fid = f"F{i + 1}"
        valid[fid] = {"id": fid, "kind": "fact", "label": "Reported financials", "text": fact}
        blocks.append(f"[{fid}] {fact}")
    if not pages:
        return {"business": None, "segments": [], "bull": [], "bear": [], "sources_used": 0}

    result = llm.complete(conn, "bull_bear", f"Company: {name}\n\n" + "\n\n".join(blocks), system=SYSTEM, max_tokens=12000)
    data = result.data if isinstance(result.data, dict) else {}

    def points(raw) -> list[dict]:
        out = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("point"), str):
                continue
            cites = _cites(item.get("cites"), valid)
            if cites:  # an uncited claim is not shown
                out.append({"point": " ".join(item["point"].split()), "cites": cites})
        return out[:3]

    business = None
    raw_business = data.get("business")
    if isinstance(raw_business, dict) and isinstance(raw_business.get("text"), str):
        cites = _cites(raw_business.get("cites"), valid)
        if cites:
            business = {"text": " ".join(raw_business["text"].split()), "cites": cites}

    segments = []
    for item in data.get("segments", []) if isinstance(data.get("segments"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        cites = _cites(item.get("cites"), valid)
        if not cites:
            continue
        share = item.get("share")
        note = item.get("note")
        segments.append({"name": item["name"].strip()[:60],
                         "share": str(share).strip()[:12] if share not in (None, "", "null") else None,
                         "note": note.strip()[:90] if isinstance(note, str) and note.strip().lower() != "null" else None,
                         "cites": cites})
    return {"business": business, "segments": segments[:8], "bull": points(data.get("bull")),
            "bear": points(data.get("bear")), "sources_used": len(pages)}
