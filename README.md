# FINN

A mobile-first investment agent that filters. Across a portfolio of 20 NSE stocks it
surfaces the few filings that matter, says why in one line, and buries the rest.

> Status: work in progress (build challenge, deadline 15 Nov 2026). The Brief, Alerts and
> Settings screens run on real data. Research (Promise Tracker, cited Q&A) is next. This
> README will grow into the full write-up; for now it covers how to run what exists.

## Run it locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python ingest/fetch.py        # prices + announcements into data/finn.db
.venv/Scripts/python ingest/process.py      # classify, build cards, rank, write the snapshot
cd frontend && npm install && npm run build && npm start    # http://localhost:3000
```

The app runs from the committed snapshot (`frontend/public/snapshot.json`), so the last
command alone is enough to see it. The API is optional:
`cd backend && ../.venv/Scripts/uvicorn app:app` then set `NEXT_PUBLIC_API_URL`.

Tests: `cd backend && ../.venv/Scripts/python -m pytest -q`

## How it is put together

```
ingest/fetch.py  ──►  SQLite  ──►  ingest/process.py  ──►  snapshot.json  ──►  Next.js app
 yfinance (EOD)                     1. rules classify (free)                    Brief · Alerts
 NSE announcements                  2. cheap model: only the ambiguous rest     Research · Settings
 screener.in                        3. cards for material filings
                                    4. rank in code, with reasons
```

- `backend/finn/` — sources, classifier, ranking, alerts, results maths, model router.
- `ingest/` — the two jobs above.
- `frontend/` — Next.js app; reads the snapshot first, then a fresher one from the API.
- `docs/BUILD_LOG.md` — decisions, dead ends and fixes, session by session.
- `docs/AI_HISTORY.md` — the AI sessions used to build this.

Model keys are optional (`.env.example`). Without one, FINN runs on rules and code, and
results cards use screener.in's standardised table, labelled as such.
