"""SQLite storage. One file, no ORM: the schema is small and the queries are simple."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    symbol      TEXT NOT NULL,
    date        TEXT NOT NULL,          -- YYYY-MM-DD (IST trading day)
    close       REAL NOT NULL,
    prev_close  REAL,
    pct_change  REAL,                   -- vs previous close, in %
    volume      INTEGER,
    avg_vol_20  REAL,                   -- mean volume of the 20 sessions BEFORE this one
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS announcements (
    id             TEXT PRIMARY KEY,    -- exchange sequence id
    symbol         TEXT NOT NULL,
    company        TEXT,
    ts             TEXT NOT NULL,       -- ISO 8601, IST
    exch_category  TEXT,                -- the exchange's own subject/category
    subject        TEXT,                -- free-text description from the filing
    attachment_url TEXT,
    source         TEXT NOT NULL,       -- NSE | BSE
    category       TEXT,                -- FINN category
    cat_method     TEXT,                -- rule | llm
    cat_rule       TEXT,                -- which rule fired (for transparency / debugging)
    kind           TEXT,                -- finer label inside a category, used by ranking
    summary        TEXT,                -- one-line summary for material items
    detail         TEXT                 -- JSON: results card, people card, etc.
);
CREATE INDEX IF NOT EXISTS idx_ann_ts ON announcements (ts);
CREATE INDEX IF NOT EXISTS idx_ann_symbol ON announcements (symbol, ts);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None
