"""Classify, enrich, rank and export the snapshot. Safe to re-run: it only touches new rows.

Run: python ingest/process.py

Pipeline, cheapest step first:
  1. rules classify every new filing (free);
  2. the cheap model labels only what the rules could not place;
  3. material filings get a card (results numbers, people, one-line summary);
  4. everything is ranked in code and written to the snapshot the app reads.
Steps 2 and the model parts of 3 are skipped when no model key is configured; the
app still works, with results cards from the screener fallback.
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

from finn import db, enrich, llm, llm_tasks, snapshot  # noqa: E402


def main() -> int:
    with db.session() as conn:
        if conn.execute("SELECT COUNT(*) c FROM announcements").fetchone()["c"] == 0:
            # Sources were unreachable on a fresh database: keep the snapshot we have
            # rather than publish an empty one. Still record why, or the failure is
            # invisible and /health keeps reporting "ok" over data nothing refreshed.
            print("no filings in the database; leaving the existing snapshot untouched")
            if snapshot.refresh_ingest_meta(conn):
                print("recorded this run's ingest status so /health reports it")
            return 0
        counts = snapshot.classify_pending(conn)
        conn.commit()
        print(f"rules: {counts}")

        if llm.available("cheap"):
            try:
                print(f"model-classified: {enrich.classify_ambiguous(conn)}")
                print(f"results cards: {enrich.enrich_results(conn, llm_tasks.results_extractor(conn), redo_fallbacks=True)}")
                print(f"people cards: {enrich.enrich_people(conn)}")
                print(f"summaries: {enrich.enrich_summaries(conn)}")
            except llm.LLMError as exc:
                # A provider outage must not cost us the snapshot: keep what we have and carry on.
                print(f"model step stopped early: {exc}")
                print(f"results cards (fallback): {enrich.enrich_results(conn)}")
        else:
            print("no model key: skipping model steps")
            print(f"results cards: {enrich.enrich_results(conn)}")

        snap = snapshot.build(conn)
    snapshot.write(snap)

    anns = snap["announcements"]
    material = [a for a in anns if a["score"] >= snap["material_threshold"]]
    print(f"{len(anns)} filings, {len(material)} material, {len(anns) - len(material)} routine")
    for cat, n in collections.Counter(a["category"] for a in anns).most_common():
        print(f"  {n:>4} {cat}")
    stats = snap["stats"]
    print(f"model usage: {stats['calls']} calls ({stats['cached']} cached), {stats['tokens']} tokens, "
          f"cost_usd={stats['cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
