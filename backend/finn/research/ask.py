"""Ask FINN: answer a question about one company from its own documents, with citations.

Retrieve the most relevant pages (BM25), give them to the model with the computed
financial facts, and require a source for every sentence. Sentences that cite nothing
valid are removed in code; if nothing survives, the answer is "Not disclosed in the sources."
"""
from __future__ import annotations

import sqlite3

from .. import llm
from .corpus import index_for

TOP_PAGES = 8
PAGE_CHARS = 2800
NOT_DISCLOSED = "Not disclosed in the sources."

EXPAND_SYSTEM = """An investor asks a question about an Indian listed company. To search the company's annual report and
earnings-call transcripts by keyword, give 3 short search phrases (3 to 7 words each) that use the vocabulary those
documents would use, including likely synonyms (for example: customer, client, account; attrition, employee turnover;
debt, borrowings). Do not answer the question.
Reply with JSON only: {"queries": ["...", "...", "..."]}"""


def expand(conn: sqlite3.Connection, question: str) -> list[str]:
    """Extra phrasings of the question for keyword search. Cheap model; the question alone on any failure."""
    try:
        result = llm.complete(conn, "expand_query", question, system=EXPAND_SYSTEM, max_tokens=300)
    except (llm.LLMError, llm.LLMUnavailable):
        return []
    raw = result.data.get("queries", []) if isinstance(result.data, dict) else []
    return [" ".join(q.split())[:120] for q in raw if isinstance(q, str) and q.strip()][:3]


def retrieve(conn: sqlite3.Connection, corpus: dict, question: str, k: int = TOP_PAGES) -> list[dict]:
    """Search with the question and its expansions, then merge by reciprocal rank so a page
    that ranks well for any phrasing is kept."""
    index = index_for(corpus)
    fused: dict[tuple[str, int], float] = {}
    pages: dict[tuple[str, int], dict] = {}
    for weight, query in [(1.5, question)] + [(1.0, q) for q in expand(conn, question)]:
        for rank, hit in enumerate(index.search(query, k=k)):
            key = (hit["doc"], hit["page"])
            pages[key] = hit
            fused[key] = fused.get(key, 0.0) + weight / (20 + rank)
    return [pages[key] for key in sorted(fused, key=fused.get, reverse=True)[:k]]


SYSTEM = """You answer an investor's question about one Indian listed company using ONLY the numbered sources below.
Sources 1, 2, ... are pages from the company's annual report and earnings-call transcripts. Source F holds figures
computed from its reported financials.

Rules:
  - Use nothing beyond these sources: no news, no outside knowledge of the company, no guesses.
  - Every sentence must list the sources that support it.
  - If the sources do not answer the question, set not_disclosed to true and return no sentences.
    If they answer only part of it, answer that part and say plainly what is not disclosed.
  - Be direct: at most 5 sentences, numbers where the sources give them, no preamble.

Reply with JSON only:
{"not_disclosed": true or false, "sentences": [{"text": "...", "cites": [1, "F"]}]}"""


def answer(conn: sqlite3.Connection, corpus: dict, facts: list[str], question: str) -> dict:
    question = " ".join(question.split())[:400]
    doc_by_id = {d["id"]: d for d in corpus["docs"]}
    hits = retrieve(conn, corpus, question)
    valid: dict[str, dict] = {}
    blocks = []
    for i, p in enumerate(hits):
        doc = doc_by_id[p["doc"]]
        valid[str(i + 1)] = {"doc": doc["id"], "label": f"{doc['short']} p.{p['page']}", "page": p["page"],
                             "url": f"{doc['url']}#page={p['page']}", "kind": "page"}
        blocks.append(f"[{i + 1}] {doc['label']}, page {p['page']}\n{p['text'][:PAGE_CHARS]}")
    if facts:
        valid["F"] = {"doc": None, "label": "Reported financials", "page": None, "url": None, "kind": "fact"}
        blocks.append("[F] Figures computed from reported financials:\n" + "\n".join(f"- {f}" for f in facts))
    if not blocks:
        return {"question": question, "not_disclosed": True, "sentences": [{"text": NOT_DISCLOSED, "cites": []}],
                "sources": []}

    result = llm.complete(conn, "qa", f"Question: {question}\n\n" + "\n\n".join(blocks), system=SYSTEM, max_tokens=8000)
    data = result.data if isinstance(result.data, dict) else {}
    sentences = []
    for item in data.get("sentences", []) if isinstance(data.get("sentences"), list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            continue
        cites, seen = [], set()
        for c in item.get("cites", []) if isinstance(item.get("cites"), list) else []:
            key = str(c).strip().strip("[]")
            if key in valid and key not in seen:
                seen.add(key)
                cites.append(valid[key])
        if cites:  # strip any sentence the model could not tie to a source
            sentences.append({"text": " ".join(item["text"].split()), "cites": cites})
    if data.get("not_disclosed") is True or not sentences:
        return {"question": question, "not_disclosed": True, "sentences": [{"text": NOT_DISCLOSED, "cites": []}],
                "sources": [], "cached": result.cached}
    used = {(c["label"]): c for s in sentences for c in s["cites"]}
    return {"question": question, "not_disclosed": False, "sentences": sentences, "sources": list(used.values()),
            "cached": result.cached}
