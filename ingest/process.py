"""Classify, rank and export the snapshot. Safe to re-run: it only touches new rows.

Run: python ingest/process.py
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from finn import db, snapshot  # noqa: E402


def main() -> int:
    with db.session() as conn:
        counts = snapshot.classify_pending(conn)
        conn.commit()
        snap = snapshot.build(conn)
    snapshot.write(snap)

    anns = snap["announcements"]
    material = [a for a in anns if a["score"] >= snap["material_threshold"]]
    print(f"classified this run: {counts}")
    print(f"{len(anns)} filings, {len(material)} material, {len(anns) - len(material)} routine")
    for cat, n in collections.Counter(a["category"] for a in anns).most_common():
        print(f"  {n:>4} {cat}")
    print("top 12:")
    for a in sorted(anns, key=lambda x: (-x["score"], x["ts"]))[:12]:
        print(f"  {a['score']:>5} {a['ts'][:10]} {a['symbol']:<11} {a['category']:<18} {(a['subject'] or '')[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
