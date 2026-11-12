"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { buildBrief, firedAlerts, headline, nearestBusyWindow, type Brief } from "@/lib/brief";
import { CATEGORY_LABEL, dateTime, dayLabel, direction, greeting, istDay, pct } from "@/lib/format";
import { update, usePrefs, type WindowKey } from "@/lib/store";
import type { Snapshot } from "@/lib/types";
import { FilingCard } from "./FilingCard";
import { ChevronIcon } from "./icons";
import { DataStamp, WithSnapshot } from "./Shell";

const WINDOWS: { key: WindowKey; label: string }[] = [
  { key: "24h", label: "24h" }, { key: "3d", label: "3 days" }, { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" }, { key: "custom", label: "Custom" },
];

function WindowPicker({ snap }: { snap: Snapshot }) {
  const prefs = usePrefs();
  const today = istDay(snap.as_of.announcements ?? snap.generated_at);
  return (
    <div>
      <div role="group" aria-label="Time window" className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4">
        {WINDOWS.map(({ key, label }) => {
          const active = prefs.window === key;
          return (
            <button key={key} type="button" aria-pressed={active}
              onClick={() => update({
                window: key,
                ...(key === "custom" && !prefs.customFrom ? { customFrom: today, customTo: today } : {}),
              })}
              className={`h-9 shrink-0 rounded-full border px-3.5 text-[13px] font-medium ${
                active ? "border-ink bg-ink text-bg" : "border-line bg-surface text-muted"}`}>
              {label}
            </button>
          );
        })}
      </div>
      {prefs.window === "custom" && (
        <div className="mt-2 flex items-center gap-2 text-[13px] text-muted">
          <input type="date" aria-label="From" value={prefs.customFrom ?? today} max={prefs.customTo ?? today}
            onChange={(e) => update({ customFrom: e.target.value })}
            className="num h-10 min-w-0 flex-1 rounded-md border border-line bg-surface px-2 text-ink" />
          to
          <input type="date" aria-label="To" value={prefs.customTo ?? today} min={prefs.customFrom ?? undefined} max={today}
            onChange={(e) => update({ customTo: e.target.value })}
            className="num h-10 min-w-0 flex-1 rounded-md border border-line bg-surface px-2 text-ink" />
        </div>
      )}
    </div>
  );
}

function Movers({ snap, brief }: { snap: Snapshot; brief: Brief }) {
  const { settings } = usePrefs();
  const alerts = firedAlerts(snap, settings, istDay(brief.range.start.toISOString()), istDay(brief.range.end.toISOString()));
  if (alerts.length === 0) return null;
  return (
    <section aria-label="Unusual moves" className="mt-4">
      <div className="flex items-baseline justify-between">
        <h2 className="label">{alerts.length} unusual {alerts.length === 1 ? "move" : "moves"} in the market</h2>
        <Link href="/alerts" className="text-[12px] font-medium text-accent">All alerts</Link>
      </div>
      <ul className="no-scrollbar -mx-4 mt-1.5 flex gap-2 overflow-x-auto px-4">
        {alerts.slice(0, 8).map((a) => (
          <li key={a.id} className="shrink-0 rounded-2xl border border-line bg-surface px-3.5 py-2.5">
            <p className="tick text-[13px] font-semibold">{a.symbol}</p>
            <p className={`num text-[13px] font-medium ${a.type === "price" ? direction(a.value) : "text-ink"}`}>
              {a.type === "price" ? pct(a.value) : `${a.value.toFixed(1)}x vol`}
            </p>
            <p className="num text-[11px] text-faint">{a.date.slice(8)}/{a.date.slice(5, 7)}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Routine({ brief }: { brief: Brief }) {
  const [open, setOpen] = useState(false);
  if (brief.routineCount === 0) return null;
  return (
    <section className="mt-4 card">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="flex h-12 w-full items-center gap-2 px-3.5 text-left text-[14px]">
        <span><span className="num font-semibold">{brief.routineCount}</span> routine filing{brief.routineCount > 1 ? "s" : ""} hidden</span>
        <ChevronIcon className={`ml-auto text-muted ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="border-t border-line px-3.5 pb-3">
          {brief.routine.map(({ category, items }) => (
            <details key={category} className="group border-b border-line last:border-0">
              <summary className="flex h-11 cursor-pointer list-none items-center text-[13px]">
                <span className="font-medium">{CATEGORY_LABEL[category]}</span>
                <span className="num ml-2 text-muted">{items.length}</span>
                <ChevronIcon width={16} height={16} className="ml-auto text-faint group-open:rotate-180" />
              </summary>
              <ul className="space-y-2 pb-3">
                {items.map((a) => (
                  <li key={a.id} className="flex gap-2 text-[12px] leading-4">
                    <span className="tick w-[78px] shrink-0 truncate font-medium">{a.symbol}</span>
                    {a.url
                      ? <a href={a.url} target="_blank" rel="noreferrer" className="line-clamp-2 text-muted underline decoration-line underline-offset-2">{a.title}</a>
                      : <span className="line-clamp-2 text-muted">{a.title}</span>}
                  </li>
                ))}
              </ul>
            </details>
          ))}
        </div>
      )}
    </section>
  );
}

function Ready({ snap, source, refreshing, liveError }: {
  snap: Snapshot; source: string; refreshing: boolean; liveError?: string | null;
}) {
  const prefs = usePrefs();
  const brief = useMemo(() => buildBrief(snap, prefs), [snap, prefs]);
  const [showSeen, setShowSeen] = useState(false);
  const now = new Date();
  const empty = brief.material.length === 0 && brief.seen.length === 0;
  const wider = useMemo(() => (empty ? nearestBusyWindow(snap, prefs) : null), [empty, snap, prefs]);
  const widerLabel = WINDOWS.find((w) => w.key === wider)?.label;
  const emptyWindowPhrase = prefs.window === "custom"
    ? "Nothing new in the dates you picked."
    : `Nothing new in the last ${(WINDOWS.find((w) => w.key === prefs.window)?.label ?? "window").toLowerCase()}.`;

  // An evaluator may open this days after the last ingestion. Rather than a blank page,
  // widen to the nearest window that has something and say so. The chosen window stays
  // selected, so this explains itself instead of silently overriding the choice.
  const fallback = useMemo(
    () => (wider ? buildBrief(snap, { ...prefs, window: wider }) : null),
    [wider, snap, prefs],
  );
  const shown = fallback ?? brief;
  const lines = useMemo(() => headline(shown, snap), [shown, snap]);
  const latestFilingTs = useMemo(
    () => snap.announcements.reduce<string | null>((m, a) => (m === null || a.ts > m ? a.ts : m), null),
    [snap],
  );

  return (
    <>
      <header className="pb-3 pt-2">
        <p className="text-[13px] font-medium text-accent">{greeting(now)}. Here is your brief.</p>
        <h1 className="display mt-1 text-[30px] leading-9">
          {shown.material.length + shown.seen.length === 0
            ? "Nothing needs you right now."
            : `${shown.material.length + shown.seen.length} of ${shown.total} filings are worth your time.`}
        </h1>
        <p className="num mt-1.5 text-[13px] text-muted">
          {snap.portfolio.length} companies · {dateTime(shown.range.start.toISOString())} to {dateTime(shown.range.end.toISOString())}
        </p>
      </header>

      <WindowPicker snap={snap} />

      {fallback && (
        <section aria-label="Window widened" className="mt-4 rounded-[18px] border border-line bg-sunken px-4 py-3.5">
          <p className="text-[15px] font-medium leading-[23px]">{emptyWindowPhrase}</p>
          <p className="mt-1 text-[13px] leading-5 text-muted">
            {latestFilingTs
              ? <>The latest filings are from {dayLabel(latestFilingTs)}. Showing the last {widerLabel?.toLowerCase()} instead.</>
              : <>Showing the last {widerLabel?.toLowerCase()} instead.</>}
          </p>
          <button type="button" onClick={() => wider && update({ window: wider })}
            className="mt-3 h-9 rounded-md border border-line bg-surface px-3.5 text-[13px] font-medium">
            Keep the last {widerLabel?.toLowerCase()}
          </button>
        </section>
      )}

      {lines.length > 0 && (
        <section aria-label="Summary" className="mt-4 rounded-[18px] bg-sunken px-4 py-3.5">
          <p className="label mb-1">In short</p>
          {lines.map((l) => <p key={l} className="text-[15px] leading-[23px]">{l}</p>)}
        </section>
      )}

      <Movers snap={snap} brief={shown} />

      <section aria-label="Material filings" className="mt-4 space-y-3">
        {shown.material.map((c) => <FilingCard key={c.head.id} cluster={c} now={now} />)}
        {shown.material.length === 0 && (
          <div className="rounded-[18px] border border-dashed border-line px-4 py-8 text-center">
            <p className="text-[15px] font-medium">
              {shown.seen.length > 0 ? "You are caught up." : "Quiet stretch. Nothing material to show."}
            </p>
            <p className="mt-1 text-[13px] text-muted">
              {shown.total > 0
                ? `${shown.routineCount} routine filing${shown.routineCount === 1 ? "" : "s"} below, none needing attention.`
                : latestFilingTs
                  ? `No material filings from your portfolio. The latest on record is from ${dayLabel(latestFilingTs)}.`
                  : "No filings from your portfolio yet."}
            </p>
          </div>
        )}
      </section>

      {shown.seen.length > 0 && (
        <section className="mt-4">
          <button type="button" onClick={() => setShowSeen(!showSeen)} aria-expanded={showSeen}
            className="flex h-10 items-center gap-1 text-[13px] font-medium text-muted">
            <ChevronIcon width={16} height={16} className={showSeen ? "rotate-180" : ""} />
            {shown.seen.length} seen
          </button>
          {showSeen && <div className="space-y-3">{shown.seen.map((c) => <FilingCard key={c.head.id} cluster={c} now={now} />)}</div>}
        </section>
      )}

      <Routine brief={shown} />

      <footer className="mt-5 space-y-1">
        <DataStamp snap={snap} source={source} refreshing={refreshing} liveError={liveError} />
        <p className="num text-[11px] text-faint">
          {snap.stats && snap.stats.calls > 0 ? (
            <>
              Model cost of this data:{" "}
              {snap.stats.cost_inr !== null ? `₹${snap.stats.cost_inr.toFixed(2)}`
                : snap.stats.cost_usd !== null ? `$${snap.stats.cost_usd.toFixed(4)}` : "not priced"}
              {" · "}{snap.stats.tokens.toLocaleString("en-IN")} tokens · {snap.stats.calls} calls,{" "}
              {snap.stats.cached} from cache
            </>
          ) : (
            "Model cost of this data: ₹0. Classified by rules, numbers computed in code."
          )}
        </p>
      </footer>
    </>
  );
}

export function BriefScreen() {
  return <WithSnapshot>{(snap, meta) => <Ready snap={snap} {...meta} />}</WithSnapshot>;
}
