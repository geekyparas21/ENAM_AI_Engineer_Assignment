"""Build research for one or more tickers and publish it for the app.

Run: python ingest/research.py KPITTECH DIXON      (any NSE symbols)
     python ingest/research.py --publish           (only re-export what is already built)

Each build writes data/research/<SYMBOL>/research.json. Publishing copies those files to
frontend/public/research/ so the deployed app can show them without the backend.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from finn import db  # noqa: E402
from finn.research import engine  # noqa: E402

PUBLIC = ROOT / "frontend" / "public" / "research"


def publish() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    index = engine.available()
    for item in index:
        data = engine.load(item["symbol"])
        (PUBLIC / f"{item['symbol']}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (PUBLIC / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    print(f"published {len(index)} research files: {', '.join(i['symbol'] for i in index)}")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    refresh = "--refresh" in sys.argv
    failed = []
    for symbol in args:
        started = time.time()
        print(f"== {symbol}")
        try:
            with db.session() as conn:
                result = engine.build(conn, symbol, lambda m, i, n: print(f"   [{i}/{n}] {m}"), refresh=refresh)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the batch
            failed.append(symbol)
            print(f"   FAILED: {exc}")
            continue
        card, usage = result["promises"]["scorecard"], result["usage"]
        print(f"   {card['total']} promise threads {card['counts']}; bull {len(result['bull'])}, bear {len(result['bear'])}; "
              f"{usage['tokens']} tokens, ${usage['cost_usd']} list price; {time.time() - started:.0f}s")
        for w in result["warnings"]:
            print(f"   warning: {w}")
    publish()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
