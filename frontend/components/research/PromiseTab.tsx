"use client";

import { useState } from "react";
import type { PromiseThread, Research, Verdict } from "@/lib/research";
import { CheckIcon, ChevronIcon, ClockIcon, FadeIcon, HelpIcon, ShiftIcon, XIcon } from "../icons";
import { TargetBar } from "./Charts";

type IconType = typeof CheckIcon;

export const VERDICT: Record<Verdict, { label: string; text: string; fill: string; Icon: IconType }> = {
  delivered: { label: "Delivered", text: "text-up", fill: "var(--up)", Icon: CheckIcon },
  missed: { label: "Missed", text: "text-down", fill: "var(--down)", Icon: XIcon },
  moved_goalposts: { label: "Moved the goalposts", text: "text-warn", fill: "var(--warn)", Icon: ShiftIcon },
  quietly_dropped: { label: "Quietly dropped", text: "text-warn", fill: "var(--muted)", Icon: FadeIcon },
  in_progress: { label: "In progress", text: "text-accent", fill: "var(--chart)", Icon: ClockIcon },
  unverifiable: { label: "Not verifiable", text: "text-muted", fill: "var(--line)", Icon: HelpIcon },
};
const ORDER: Verdict[] = ["delivered", "missed", "moved_goalposts", "quietly_dropped", "in_progress", "unverifiable"];
const PROGRESS = { ahead: "ahead of target", on_track: "on track", behind: "behind target" } as const;

function Scorecard({ research }: { research: Research }) {
  const { scorecard, statements_found, calls } = research.promises;
  const kept = scorecard.counts.delivered;
  const present = ORDER.filter((v) => scorecard.counts[v] > 0);
  return (
    <section className="rounded-xl border border-line bg-surface p-3.5">
      <p className="label">Say-do record · last {calls.length} calls</p>
      {scorecard.settled > 0 ? (
        <p className="mt-1 text-[15px] leading-[22px]">
          <span className="text-[28px] font-semibold leading-8 tracking-tight">{kept} of {scorecard.settled}</span>{" "}
          promises that could be scored were kept as stated.
        </p>
      ) : (
        <p className="mt-1 text-[15px] leading-[22px]">No promise has reached its deadline yet; all are still open or not checkable.</p>
      )}
      {/* One whole, split by verdict: a thin segmented bar; the list beside it carries names and counts. */}
      <div className="mt-3 flex h-2 gap-0.5" role="img"
        aria-label={present.map((v) => `${scorecard.counts[v]} ${VERDICT[v].label}`).join(", ")}>
        {present.map((v, i) => (
          <span key={v} style={{ flexGrow: scorecard.counts[v], background: VERDICT[v].fill }}
            className={`h-2 ${i === 0 ? "rounded-l-full" : ""} ${i === present.length - 1 ? "rounded-r-full" : ""}`} />
        ))}
      </div>
      <ul className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1">
        {present.map((v) => (
          <li key={v} className="flex items-center gap-1.5 text-[12px] text-muted">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: VERDICT[v].fill }} />
            <span className="num font-semibold text-ink">{scorecard.counts[v]}</span>
            <span className="truncate">{VERDICT[v].label}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2.5 text-[11px] leading-4 text-faint">
        {statements_found} guidance statements found; each quote was checked against its transcript page. Delivered
        figures are computed from reported financials.
      </p>
    </section>
  );
}

function Thread({ t }: { t: PromiseThread }) {
  const [open, setOpen] = useState(false);
  const meta = VERDICT[t.verdict];
  const first = t.delivered[0];
  // The target-versus-delivered bar is drawn only when the two are genuinely comparable:
  // a settled or in-progress verdict, same period, same basis, both in percent.
  const scored = t.verdict === "delivered" || t.verdict === "missed" || t.verdict === "in_progress";
  const numeric = scored && first && first.on_period && first.unit === "%" && t.basis === "reported" &&
    (t.target.low !== null || t.target.high !== null) && (t.target.unit === "%" || t.target.unit === null);
  const changed = t.initial_target && t.target.text && t.initial_target !== t.target.text;

  return (
    <article className="rounded-xl border border-line bg-surface p-3.5">
      <header className="flex items-center gap-2">
        <span className={`flex items-center gap-1 text-[12px] font-semibold ${meta.text}`}>
          <meta.Icon width={15} height={15} />
          {meta.label}{t.progress ? `, ${PROGRESS[t.progress]}` : ""}
        </span>
        {t.period && <span className="num ml-auto shrink-0 text-[11px] text-faint">{t.period}</span>}
      </header>
      <h3 className="mt-1.5 text-[15px] font-medium leading-[21px]">{t.title}</h3>

      <dl className="mt-2 space-y-1 text-[13px] leading-[19px]">
        <div className="flex gap-2">
          <dt className="w-[72px] shrink-0 text-muted">Said</dt>
          <dd className="min-w-0">
            {changed ? <>{t.initial_target} <span className="text-muted">then</span> {t.target.text}</> : (t.target.text ?? t.initial_target)}
          </dd>
        </div>
        {!numeric && t.delivered.map((d) => (
          <div key={d.key} className="flex gap-2">
            <dt className="w-[72px] shrink-0 text-muted">{d.on_period ? "Delivered" : "Latest"}</dt>
            <dd className="num min-w-0"><span className="font-medium">{d.text}</span> <span className="text-muted">{d.label}</span></dd>
          </div>
        ))}
      </dl>

      {numeric && (
        <div className="mt-2">
          <TargetBar low={t.target.low} high={t.target.high} delivered={first.value} unit="%"
            tone={t.verdict === "delivered" ? "up" : t.verdict === "missed" ? "down" : "ink"} />
          <p className="num text-[11px] text-faint">{first.label}{first.partial ? ", year not complete" : ""}</p>
        </div>
      )}

      <p className="mt-2 text-[13px] leading-[19px]">{t.evidence}</p>
      {t.checked_by_code && (
        <p className="mt-1 text-[11px] text-faint">Verdict re-checked in code against the reported figure.</p>
      )}

      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
        className="-mb-1 mt-2 flex h-9 items-center gap-1 text-[12px] font-medium text-muted">
        <ChevronIcon width={14} height={14} className={open ? "rotate-180" : ""} />
        What management said · {t.history.length} {t.history.length === 1 ? "call" : "calls"}
      </button>
      {open && (
        <ol className="mt-1 space-y-2.5 border-l-2 border-line pl-3">
          {t.history.map((h) => (
            <li key={`${h.call}-${h.page}-${h.quote.slice(0, 12)}`}>
              <p className="num flex flex-wrap items-baseline gap-x-2 text-[12px]">
                <span className="font-semibold">{h.call_label}</span>
                {h.target && <span className="text-muted">{h.target}</span>}
                <a href={h.url} target="_blank" rel="noreferrer" className="ml-auto font-medium text-accent">p.{h.page}</a>
              </p>
              <blockquote className="mt-0.5 text-[13px] leading-[19px] text-muted">“{h.quote}”</blockquote>
              {h.speaker && <p className="text-[11px] text-faint">{h.speaker}</p>}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

export function PromiseTab({ research }: { research: Research }) {
  const { threads } = research.promises;
  if (threads.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-[13px] text-muted">
        No explicit guidance was found in the last {research.promises.calls.length || "few"} concall transcripts, so there is
        nothing to hold management to here.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <Scorecard research={research} />
      {threads.map((t) => <Thread key={t.id} t={t} />)}
    </div>
  );
}
