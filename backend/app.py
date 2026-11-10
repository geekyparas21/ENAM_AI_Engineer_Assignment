"""FINN API. Reads processed data only; it never calls a live exchange in a request.

Run: uvicorn app:app --reload   (from the backend/ directory)
"""
from __future__ import annotations

import json
import os

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from finn import alerts, db, snapshot
from finn.config import DB_PATH, DEFAULT_SETTINGS, PORTFOLIO, SNAPSHOT_PATH

app = FastAPI(title="FINN API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("FINN_CORS_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def load_snapshot() -> dict:
    """Live database if this instance has one, otherwise the committed seed snapshot."""
    if DB_PATH.exists():
        with db.session() as conn:
            if conn.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"]:
                return snapshot.build(conn)
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "has_db": DB_PATH.exists(), "has_snapshot": SNAPSHOT_PATH.exists()}


@app.get("/api/snapshot")
def get_snapshot() -> dict:
    return load_snapshot()


@app.get("/api/stats")
def get_stats() -> dict:
    """Model usage and cost: totals and the per-task breakdown behind the README table."""
    return load_snapshot().get("stats") or {"calls": 0, "cached": 0, "tokens": 0, "cost_usd": None, "by_task": []}


@app.get("/api/alerts")
def get_alerts(
    volume_multiple: float = Query(DEFAULT_SETTINGS["volume_multiple"], gt=1, le=20),
    price_move_pct: float = Query(DEFAULT_SETTINGS["price_move_pct"], gt=0, le=50),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    snap = load_snapshot()
    rows = [d for sym in PORTFOLIO for d in snap["market"].get(sym, [])[-days:]]
    return {
        "thresholds": {"volume_multiple": volume_multiple, "price_move_pct": price_move_pct},
        "alerts": alerts.evaluate(rows, volume_multiple, price_move_pct),
    }


# --- Research (pull side) -----------------------------------------------------------------
# A ticker that has been researched is served from its file. A new ticker is built on
# demand, with progress streamed to the client so the first-time wait is visible.

import queue  # noqa: E402
import re  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from finn import llm  # noqa: E402
from finn.research import ask as ask_mod  # noqa: E402
from finn.research import corpus as corpus_mod  # noqa: E402
from finn.research import engine  # noqa: E402
from finn.sources.screener import ScreenerError  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

SYMBOL = re.compile(r"[A-Z0-9&\-]{1,20}")
_build_locks: dict[str, threading.Lock] = {}
_build_slots = threading.Semaphore(2)          # at most two tickers being built at once
_recent_asks: list[float] = []
MAX_ASKS_PER_MINUTE = 20                       # protects the free-tier model quota


def _symbol(raw: str) -> str:
    symbol = raw.upper().strip()
    if not SYMBOL.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="Not a valid NSE symbol.")
    return symbol


@app.get("/api/research")
def research_index() -> dict:
    return {"available": engine.available(), "model_ready": llm.available("cheap") and llm.available("strong")}


@app.get("/api/research/{symbol}")
def research_get(symbol: str) -> dict:
    data = engine.load(_symbol(symbol))
    if data is None:
        raise HTTPException(status_code=404, detail="Not researched yet.")
    return data


@app.get("/api/research/{symbol}/build")
def research_build(symbol: str, refresh: bool = False) -> StreamingResponse:
    """Server-sent events: {"type": "progress", ...} lines, then one "done" or "error"."""
    symbol = _symbol(symbol)
    events: queue.Queue = queue.Queue()

    def work() -> None:
        lock = _build_locks.setdefault(symbol, threading.Lock())
        with _build_slots, lock:
            try:
                existing = None if refresh else engine.load(symbol)
                if existing is None:
                    with db.session() as conn:
                        engine.build(conn, symbol, lambda m, i, n: events.put(
                            {"type": "progress", "message": m, "step": i, "steps": n}), refresh=refresh)
                events.put({"type": "done", "symbol": symbol})
            except ScreenerError as exc:
                events.put({"type": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001 - reported to the client, never a silent hang
                events.put({"type": "error", "message": f"Research failed: {str(exc)[:200]}"})

    threading.Thread(target=work, daemon=True).start()

    def stream():
        while True:
            try:
                event = events.get(timeout=10)
            except queue.Empty:
                yield ": keep-alive\n\n"   # stops proxies closing a quiet connection
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event["type"] in ("done", "error"):
                return

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class Question(BaseModel):
    symbol: str
    question: str = Field(min_length=3, max_length=400)


@app.post("/api/ask")
def ask(body: Question) -> dict:
    symbol = _symbol(body.symbol)
    corpus = corpus_mod.load(symbol)
    research = engine.load(symbol)
    if corpus is None or research is None:
        raise HTTPException(status_code=404, detail="Research this company first.")
    if not llm.available("strong"):
        raise HTTPException(status_code=503, detail="No model key is configured on the server.")
    now = time.time()
    _recent_asks[:] = [t for t in _recent_asks if now - t < 60]
    if len(_recent_asks) >= MAX_ASKS_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many questions right now. Try again in a minute.")
    _recent_asks.append(now)
    try:
        with db.session() as conn:
            return ask_mod.answer(conn, corpus, research.get("facts", []), body.question)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=f"The model could not answer: {str(exc)[:160]}") from exc
