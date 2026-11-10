"use client";

import { useState } from "react";
import { direction, pct, price } from "@/lib/format";
import type { Holding, Snapshot } from "@/lib/types";
import { SearchIcon } from "./icons";
import { PageTitle, WithSnapshot } from "./Shell";

function Spark({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * 64).toFixed(1)},${(22 - ((v - min) / span) * 20).toFixed(1)}`)
    .join(" ");
  return (
    <svg width="64" height="24" viewBox="0 0 64 24" aria-hidden="true" className={up ? "text-up" : "text-down"}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function Row({ h }: { h: Holding }) {
  const first = h.spark[0];
  const last = h.spark[h.spark.length - 1];
  return (
    <li className="flex h-14 items-center gap-3 border-b border-line last:border-0">
      <div className="min-w-0 flex-1">
        <p className="tick text-[14px] font-semibold">{h.symbol}</p>
        <p className="truncate text-[12px] text-muted">{h.sector}</p>
      </div>
      <Spark values={h.spark} up={last >= first} />
      <div className="w-[88px] text-right">
        <p className="num text-[13px] font-medium">{price(h.close)}</p>
        <p className={`num text-[12px] ${direction(h.pct_change)}`}>{pct(h.pct_change, 2)}</p>
      </div>
    </li>
  );
}

function Ready({ snap }: { snap: Snapshot }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toUpperCase();
  const rows = snap.portfolio.filter((h) => !q || h.symbol.includes(q) || h.company.toUpperCase().includes(q));
  return (
    <>
      <PageTitle title="Research" sub="Any NSE ticker, answered only from annual reports and concall transcripts." />
      <label className="flex h-12 items-center gap-2 rounded-xl border border-line bg-surface px-3">
        <SearchIcon className="text-muted" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ticker or company"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} aria-label="Ticker or company"
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-faint" />
      </label>
      <p className="mt-2 rounded-lg bg-sunken px-3 py-2 text-[12px] leading-[18px] text-muted">
        The research engine (Promise Tracker, cited Q&A) is the next build phase. Prices below are end-of-day, as of the last session.
      </p>

      <h2 className="label mt-5">Portfolio · {rows.length} · 30 sessions</h2>
      <ul className="mt-1.5 rounded-xl border border-line bg-surface px-3.5">
        {rows.map((h) => <Row key={h.symbol} h={h} />)}
        {rows.length === 0 && <li className="py-6 text-center text-[13px] text-muted">No portfolio company matches “{query}”.</li>}
      </ul>
    </>
  );
}

export function ResearchScreen() {
  return <WithSnapshot>{(snap) => <Ready snap={snap} />}</WithSnapshot>;
}
