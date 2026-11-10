"use client";

import { useState } from "react";
import type { Cluster, Ranked } from "@/lib/brief";
import { CATEGORY_LABEL, ago, dateTime, direction, pct } from "@/lib/format";
import { toggleMute, toggleSeen, toggleStar } from "@/lib/store";
import { CheckIcon, ChevronIcon, InfoIcon, LinkIcon, MuteIcon, StarIcon } from "./icons";
import { ResultsTable } from "./ResultsTable";

function Body({ a }: { a: Ranked }) {
  if (a.detail?.type === "results") return <ResultsTable detail={a.detail} />;
  if (a.detail?.type === "people") {
    return (
      <ul className="mt-3 space-y-3">
        {a.detail.people.map((p) => (
          <li key={`${p.name}-${p.role}`} className="border-l-2 border-line pl-3">
            <p className="text-[14px] font-semibold leading-5">
              {p.name}
              <span className="font-normal text-muted"> · {p.action} as {p.role}</span>
            </p>
            {p.effective && <p className="num text-[12px] text-muted">Effective {p.effective}</p>}
            {p.bio && <p className="mt-1 text-[13px] leading-5">{p.bio}</p>}
            {p.bio_source && (
              <p className="mt-1 text-[11px] text-faint">
                Background from{" "}
                {p.bio_url
                  ? <a className="underline" href={p.bio_url} target="_blank" rel="noreferrer">{p.bio_source}</a>
                  : p.bio_source}
              </p>
            )}
          </li>
        ))}
      </ul>
    );
  }
  return null;
}

function Action({ label, active, onClick, children }: {
  label: string; active?: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={active} aria-label={label} title={label}
      className={`flex h-9 items-center gap-1 whitespace-nowrap rounded-md px-1.5 text-[12px] font-medium ${
        active ? "bg-accent-soft text-accent" : "text-muted hover:bg-sunken"}`}>
      {children}
    </button>
  );
}

export function FilingCard({ cluster, now }: { cluster: Cluster; now: Date }) {
  const a = cluster.head;
  const [why, setWhy] = useState(false);
  const [more, setMore] = useState(false);
  const title = a.category === "results" && a.period ? `${a.period} results` : a.title;

  return (
    <article className={`rounded-xl border border-line bg-surface p-3.5 ${a.seen ? "opacity-60" : ""}`}>
      <header className="flex items-baseline gap-2">
        <span className="tick text-[15px] font-semibold tracking-tight">{a.symbol}</span>
        <span className="label">{CATEGORY_LABEL[a.category]}</span>
        <time className="num ml-auto shrink-0 text-[11px] text-faint" dateTime={a.ts} title={dateTime(a.ts)}>
          {ago(a.ts, now)}
        </time>
      </header>

      <h3 className="mt-1.5 line-clamp-3 text-[15px] font-medium leading-[21px]">{a.summary ?? title}</h3>
      {a.summary && a.summary !== title && a.category !== "results" && (
        <p className="mt-0.5 line-clamp-1 text-[12px] text-faint">{title}</p>
      )}

      <Body a={a} />

      {a.move && (
        <p className="mt-2.5 text-[12px] text-muted">
          Stock on {a.move.date.slice(8)}/{a.move.date.slice(5, 7)}:{" "}
          <span className={`num font-medium ${direction(a.move.pct_change)}`}>{pct(a.move.pct_change)}</span>
          {a.move.vol_ratio !== null && (
            <span className="num"> · {a.move.vol_ratio.toFixed(1)}x avg volume</span>
          )}
        </p>
      )}

      {cluster.related.length > 0 && (
        <div className="mt-2.5">
          <button type="button" onClick={() => setMore(!more)} aria-expanded={more}
            className="flex items-center gap-1 text-[12px] font-medium text-muted">
            <ChevronIcon width={14} height={14} className={more ? "rotate-180" : ""} />
            {cluster.related.length} related filing{cluster.related.length > 1 ? "s" : ""} same day
          </button>
          {more && (
            <ul className="mt-1.5 space-y-1.5">
              {cluster.related.map((r) => (
                <li key={r.id} className="text-[12px] leading-4">
                  {r.url
                    ? <a href={r.url} target="_blank" rel="noreferrer" className="text-muted underline decoration-line underline-offset-2">{r.title}</a>
                    : <span className="text-muted">{r.title}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <footer className="-mx-1.5 -mb-1.5 mt-2.5 flex items-center border-t border-line pt-1.5">
        <Action label="Mark as seen" active={a.seen} onClick={() => toggleSeen(a.id)}>
          <CheckIcon width={16} height={16} />Seen
        </Action>
        <Action label="Star" active={a.starred} onClick={() => toggleStar(a.id)}>
          <StarIcon width={16} height={16} filled={a.starred} />Star
        </Action>
        <Action label={`Mute ${CATEGORY_LABEL[a.category]} for ${a.symbol}`} onClick={() => toggleMute(a.symbol, a.category)}>
          <MuteIcon width={16} height={16} />Mute
        </Action>
        <span className="ml-auto flex items-center">
          <Action label="Why this is ranked here" active={why} onClick={() => setWhy(!why)}>
            <InfoIcon width={16} height={16} /><span className="num">{Math.round(a.personalScore)}</span>
          </Action>
          {a.url && (
            <a href={a.url} target="_blank" rel="noreferrer" aria-label="Open the filing"
              className="flex h-9 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-accent">
              Filing<LinkIcon width={14} height={14} />
            </a>
          )}
        </span>
      </footer>

      {why && (
        <ol className="mt-2 space-y-0.5 rounded-md bg-sunken px-2.5 py-2 text-[12px] leading-[18px] text-muted">
          {a.personalReasons.map((r) => <li key={r}>{r}</li>)}
          <li className="text-faint">Classified by {a.method === "llm" ? "model" : "rule"} · {a.exch_category}</li>
        </ol>
      )}
    </article>
  );
}
