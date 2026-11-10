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
