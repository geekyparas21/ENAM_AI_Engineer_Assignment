"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { useSnapshot } from "@/lib/data";
import { dayLabel, direction, pct, price, shortName } from "@/lib/format";
import {
  buildResearch, hasBackend, loadIndex, loadResearch, wakeBackend,
  type BuildProgress, type IndexEntry, type Research,
} from "@/lib/research";
import type { Holding } from "@/lib/types";
import { ChevronIcon, SearchIcon } from "./icons";
import { PromiseTab } from "./research/PromiseTab";
import { AskTab, BalanceTab, CaseTab, SnapshotTab, TrajectoryTab } from "./research/Tabs";
import { PageTitle } from "./Shell";

const SYMBOL = /^[A-Z0-9&-]{1,20}$/;

// The selected company lives in the URL hash, so a research view can be shared and the
// back button works, while the page itself stays a static file.
function subscribeHash(callback: () => void) {
  window.addEventListener("hashchange", callback);
  return () => window.removeEventListener("hashchange", callback);
}
function useSymbol(): string | null {
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash, () => "");
  const symbol = decodeURIComponent(hash.replace(/^#/, "")).toUpperCase();
  return SYMBOL.test(symbol) ? symbol : null;
}
const open = (symbol: string) => { window.location.hash = encodeURIComponent(symbol.toUpperCase()); };
const close = () => { window.location.hash = ""; };

type Loaded = { symbol: string; research: Research | null; error: string | null };
type Progress = BuildProgress & { symbol: string };

const TABS = [
  { key: "promises", label: "Promises" }, { key: "snapshot", label: "Snapshot" },
  { key: "trajectory", label: "Trajectory" }, { key: "balance", label: "Balance sheet" },
  { key: "case", label: "Bull vs bear" }, { key: "ask", label: "Ask FINN" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

function View({ research }: { research: Research }) {
  const [tab, setTab] = useState<TabKey>("promises");
  const calls = research.docs.filter((d) => d.kind === "transcript" && !d.problem).length;
  const report = research.docs.find((d) => d.kind === "annual_report" && !d.problem);
  return (
    <>
      <header className="pb-3 pt-2">
        <button type="button" onClick={close} className="-ml-1 flex h-9 items-center gap-0.5 text-[13px] font-medium text-muted">
          <ChevronIcon width={16} height={16} className="rotate-90" />Companies
        </button>
        <h1 className="display mt-0.5 text-[28px] leading-8">{research.name}</h1>
        <p className="num mt-0.5 text-[12px] text-muted">
          <span className="tick font-semibold text-ink">{research.symbol}</span> · read {calls} concall
          {calls === 1 ? "" : "s"}{report ? ` and the ${report.short.replace("AR ", "")} annual report` : ""}
        </p>
      </header>

      <div role="tablist" aria-label="Research sections" className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4">
        {TABS.map(({ key, label }) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            className={`h-9 shrink-0 rounded-full border px-3.5 text-[13px] font-medium ${
              tab === key ? "border-ink bg-ink text-bg" : "border-line bg-surface text-muted"}`}>
            {label}
          </button>
        ))}
      </div>

      <div role="tabpanel" className="mt-4">
        {tab === "promises" && <PromiseTab research={research} />}
        {tab === "snapshot" && <SnapshotTab research={research} />}
        {tab === "trajectory" && <TrajectoryTab research={research} />}
        {tab === "balance" && <BalanceTab research={research} />}
        {tab === "case" && <CaseTab research={research} />}
        {tab === "ask" && <AskTab research={research} />}
      </div>

      <footer className="mt-5">
        <p className="num text-[11px] leading-4 text-faint">
          Researched {dayLabel(research.generated_at)} · {research.usage.tokens.toLocaleString("en-IN")} model tokens
          {research.usage.cost_usd !== null ? ` · $${research.usage.cost_usd.toFixed(2)} at list price, free tier used` : ""}
        </p>
      </footer>
    </>
  );
}

function Building({ symbol, progress }: { symbol: string; progress: Progress | null }) {
  const step = progress?.step ?? 0;
  const steps = progress?.steps ?? 5;
  return (
    <>
      <PageTitle title={symbol} sub="First visit: reading this company's filings now." />
      <section className="card p-4" aria-busy="true">
        <p className="text-[15px] font-medium" aria-live="polite">{progress?.message ?? "Opening the research…"}</p>
        <div className="mt-3 h-1.5 rounded-full bg-[var(--chart-soft)]" role="progressbar" aria-valuemin={0} aria-valuemax={steps} aria-valuenow={step}>
          <div className="h-1.5 rounded-full bg-[var(--chart)] transition-[width] duration-500" style={{ width: `${Math.max(6, (100 * step) / steps)}%` }} />
        </div>
        <p className="num mt-2 text-[12px] text-muted">Step {Math.min(step + 1, steps)} of {steps}</p>
        <p className="mt-3 text-[12px] leading-[18px] text-muted">
          FINN reads the last five concall transcripts and the latest annual report, then checks what management
          promised against reported numbers. This takes one to two minutes once; the next visit is instant.
        </p>
      </section>
      <button type="button" onClick={close} className="mt-3 h-10 rounded-md border border-line px-3 text-[13px] font-medium">Cancel</button>
    </>
  );
}

function Spark({ values, up }: { values: number[]; up: boolean }) {
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const span = Math.max(...values) - min || 1;
  const points = values
    .map((v, i) => `${((i / (values.length - 1)) * 56).toFixed(1)},${(20 - ((v - min) / span) * 18).toFixed(1)}`)
    .join(" ");
  return (
    <svg width="56" height="22" viewBox="0 0 56 22" aria-hidden="true" className={up ? "text-up" : "text-down"}>
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

function Picker({ index, holdings, notice }: { index: IndexEntry[]; holdings: Holding[]; notice: string | null }) {
  const [query, setQuery] = useState("");
  const q = query.trim().toUpperCase();
  const ready = new Set(index.map((e) => e.symbol));
  const rows = holdings.filter((h) => !q || h.symbol.includes(q) || h.company.toUpperCase().includes(q));
  const typedIsSymbol = SYMBOL.test(q) && !holdings.some((h) => h.symbol === q);

  return (
    <>
      <PageTitle title="Research" sub="Any NSE ticker, answered only from its annual report and concall transcripts." />
      <form onSubmit={(e) => { e.preventDefault(); if (SYMBOL.test(q)) open(q); }}
        className="flex h-12 items-center gap-2 card px-3">
        <SearchIcon className="text-muted" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="NSE ticker, e.g. KPITTECH"
          autoCapitalize="characters" autoCorrect="off" spellCheck={false} aria-label="NSE ticker"
          className="h-full min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-faint" />
        {typedIsSymbol && (
          <button type="submit" className="h-8 shrink-0 rounded-md bg-ink px-3 text-[13px] font-medium text-bg">Research</button>
        )}
      </form>
      {notice && <p role="alert" className="mt-2 rounded-lg bg-sunken px-3 py-2 text-[13px] leading-[18px] text-warn">{notice}</p>}
      {!hasBackend && (
        <p className="mt-2 text-[12px] leading-[18px] text-muted">
          Companies listed as ready open instantly. Researching a new ticker needs the research engine, which this
          build is not connected to.
        </p>
      )}

      {index.length > 0 && (
        <>
          <h2 className="label mt-5">Ready now · {index.length}</h2>
          <ul className="mt-1.5 space-y-2">
            {index.map((e) => (
              <li key={e.symbol}>
                <button type="button" onClick={() => open(e.symbol)}
                  className="flex w-full items-center gap-3 card p-3.5 text-left">
                  <span className="min-w-0 flex-1">
                    <span className="display block truncate text-[18px] leading-6">{shortName(e.name, e.symbol)}</span>
                    <span className="tick block text-[12px] text-muted">{e.symbol}</span>
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="num block text-[13px] font-medium">{e.threads} promises tracked</span>
                    <span className="num block text-[12px] text-muted">
                      {e.kept_pct === null ? "none due yet" : `kept ${e.kept_pct}% of those due`}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <h2 className="label mt-5">Your portfolio · {rows.length}</h2>
      <ul className="mt-1.5 card px-3.5">
        {rows.map((h) => {
          const canOpen = ready.has(h.symbol) || hasBackend;
          return (
            <li key={h.symbol} className="border-b border-line last:border-0">
              <button type="button" disabled={!canOpen} onClick={() => open(h.symbol)}
                className="flex h-14 w-full items-center gap-3 text-left disabled:opacity-60">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold">{shortName(h.company, h.symbol)}</span>
                  <span className="block truncate text-[12px] text-muted">
                    {ready.has(h.symbol) ? "Research ready" : hasBackend ? `${h.sector} · tap to research` : h.sector}
                  </span>
                </span>
                <Spark values={h.spark} up={h.spark[h.spark.length - 1] >= h.spark[0]} />
                <span className="w-[84px] shrink-0 text-right">
                  <span className="num block text-[13px] font-medium">{price(h.close)}</span>
                  <span className={`num block text-[12px] ${direction(h.pct_change)}`}>{pct(h.pct_change, 2)}</span>
                </span>
              </button>
            </li>
          );
        })}
        {rows.length === 0 && (
          <li className="py-6 text-center text-[13px] text-muted">
            {typedIsSymbol ? `Not in your portfolio. Press Research to look up ${q}.` : `No portfolio company matches “${query}”.`}
          </li>
        )}
      </ul>
    </>
  );
}

export function ResearchScreen() {
  const symbol = useSymbol();
  const { data: snap } = useSnapshot();
  const [index, setIndex] = useState<IndexEntry[]>([]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);

  useEffect(() => {
    wakeBackend();
    let cancelled = false;
    void loadIndex().then((entries) => { if (!cancelled) setIndex(entries); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    let cancelBuild: (() => void) | null = null;
    (async () => {
      let research = await loadResearch(symbol);
      let error: string | null = null;
      if (!research && hasBackend) {
        const job = buildResearch(symbol, (p) => { if (!cancelled) setProgress({ ...p, symbol }); });
        cancelBuild = job.cancel;
        try {
          await job.done;
          research = await loadResearch(symbol);
        } catch (e) {
          error = e instanceof Error ? e.message : "Research failed.";
        }
      } else if (!research) {
        error = `${symbol} has not been researched yet, and this build cannot research new tickers.`;
      }
      if (cancelled) return;
      setLoaded({ symbol, research, error: research ? null : (error ?? "Research could not be loaded.") });
      if (research) void loadIndex().then((entries) => { if (!cancelled) setIndex(entries); });
    })();
    return () => {
      cancelled = true;
      cancelBuild?.();
    };
  }, [symbol]);

  if (symbol) {
    const current = loaded?.symbol === symbol ? loaded : null;
    if (current?.research) return <View key={symbol} research={current.research} />;
    if (!current) return <Building symbol={symbol} progress={progress?.symbol === symbol ? progress : null} />;
    return <Picker index={index} holdings={snap?.portfolio ?? []} notice={current.error} />;
  }
  return <Picker index={index} holdings={snap?.portfolio ?? []} notice={null} />;
}
