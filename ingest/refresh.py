"""Refresh the live site in one command. Run this from your own machine.

    python ingest/refresh.py            # fetch, process, commit and push
    python ingest/refresh.py --no-push  # stop after writing the snapshot
    python ingest/refresh.py --days 7   # shorter announcement look-back

NSE answers a home connection but returns 403 to GitHub's runners, so the scheduled
workflow cannot fetch filings and this is the supported way to refresh. Pushing the
snapshot is what puts it live: Vercel redeploys on the commit.

Only the two snapshot files are ever staged, so this cannot sweep up unrelated work in
progress. It exits non-zero if ingestion recorded an error, the same rule the workflow uses.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOTS = ["data/snapshot.json", "frontend/public/snapshot.json"]

# A Windows console defaults to cp1252, which cannot encode "₹" and raises
# UnicodeEncodeError mid-run. Forced here, and passed to the child processes below, so this
# works from any shell without the caller having to remember an environment variable.
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")
CHILD_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def step(title: str, args: list[str]) -> int:
    print(f"\n=== {title} ===", flush=True)
    return subprocess.call(args, cwd=ROOT, env=CHILD_ENV)


def git(*args: str, capture: bool = False) -> str | int:
    if capture:
        return subprocess.run(["git", *args], cwd=ROOT, text=True,
                              capture_output=True).stdout.strip()
    return subprocess.call(["git", *args], cwd=ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh the FINN snapshot and publish it.")
    ap.add_argument("--days", type=int, default=30, help="announcement look-back window")
    ap.add_argument("--no-push", action="store_true", help="write the snapshot but do not publish")
    args = ap.parse_args()
    py = sys.executable

    # The fetch is allowed to fail: a blocked source must keep the previous snapshot
    # rather than publish an empty one. process.py records the reason either way.
    step("Fetching prices and announcements", [py, "ingest/fetch.py", "--days", str(args.days)])

    if step("Classifying, enriching, ranking and exporting", [py, "ingest/process.py"]) != 0:
        print("\nprocess.py failed; nothing was published.")
        return 1

    snap = json.loads((ROOT / "data/snapshot.json").read_text(encoding="utf-8"))
    ingest = snap.get("ingest") or {}
    error = ingest.get("last_error")
    print(f"\n=== Result ===\n"
          f"filings           : {len(snap['announcements'])}\n"
          f"latest filing     : {max((a['ts'] for a in snap['announcements']), default='none')}\n"
          f"last ingest ok    : {ingest.get('last_ok_at')}\n"
          f"last attempt      : {ingest.get('last_attempted_at')}\n"
          f"last error        : {error or 'none'}")

    if args.no_push:
        print("\n--no-push: the snapshot is written locally and not published.")
        return 1 if error else 0

    git("add", "--", *SNAPSHOTS)
    if git("diff", "--cached", "--quiet", "--", *SNAPSHOTS) == 0:
        print("\nThe snapshot is unchanged, so there is nothing to publish.")
        return 1 if error else 0

    print(f"\n=== Publishing ===\n{git('diff', '--cached', '--stat', '--', *SNAPSHOTS, capture=True)}")
    if git("commit", "-m", "Refresh snapshot") != 0 or git("push") != 0:
        print("\nCould not publish. The snapshot is written locally; commit and push by hand.")
        return 1
    print("\nPublished. Vercel redeploys on the push; check /health in a minute or two.")
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
