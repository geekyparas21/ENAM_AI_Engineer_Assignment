"use client";

import { useState } from "react";
import { amount } from "@/lib/format";
import { ask, hasBackend, type Answer, type Cite, type Financials, type Research } from "@/lib/research";
import { SendIcon } from "../icons";
import { ColumnChart, LineChart, RankedBars } from "./Charts";

const cr = (v: number | null) => (v === null ? "–" : `₹${amount(v)} cr`);
const pctText = (v: number | null, digits = 1) => (v === null ? "–" : `${v.toFixed(digits)}%`);
const signed = (v: number | null) => (v === null ? "–" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`);

/** A source chip: a page of a filing (opens the PDF at that page) or a computed figure. */
export function Cites({ cites }: { cites: Cite[] }) {
  const seen = new Set<string>();
  const unique = cites.filter((c) => (seen.has(c.label) ? false : (seen.add(c.label), true)));
  return (
    <span className="mt-1 flex flex-wrap gap-1">
      {unique.map((c) => c.url ? (
        <a key={c.label} href={c.url} target="_blank" rel="noreferrer"
          className="num rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-medium text-accent">{c.label}</a>
      ) : (
        <span key={c.label} className="num rounded-md bg-sunken px-1.5 py-0.5 text-[11px] text-muted" title={c.text}>
          {c.label}
        </span>
      ))}
    </span>
  );
}

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-surface p-3.5">
      {title && <h2 className="label mb-2">{title}</h2>}
      {children}
    </section>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | null)[][] }) {
  return (
    <div className="no-scrollbar -mx-1 overflow-x-auto">
      <table className="w-full border-collapse text-[12px]">
        <thead>
          <tr className="text-muted">
            {head.map((h, i) => (
              <th key={h} scope="col" className={`whitespace-nowrap px-1 pb-1 font-medium ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className="border-t border-line">
              {row.map((cell, i) => (
                <td key={i} className={`num whitespace-nowrap px-1 py-1.5 ${i === 0 ? "text-left font-medium" : "text-right"}`}>{cell ?? "–"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statValue(h: { value: number; unit: string }): string {
  if (h.unit === "cr") return `₹${amount(h.value)} cr`;
  if (h.unit === "%") return `${h.value.toFixed(1)}%`;
  return `${h.value.toFixed(h.value < 10 ? 2 : 1)}x`;
}

export function SnapshotTab({ research }: { research: Research }) {
  const f = research.financials;
  const groups = new Map<string, { name: string; share: number; note: string | null }[]>();
  const plain: Research["segments"] = [];
  for (const s of research.segments) {
    const share = s.share ? Number.parseFloat(s.share) : Number.NaN;
    if (Number.isNaN(share)) {
      plain.push(s);
      continue;
    }
    const key = s.note ?? "Revenue mix";
    groups.set(key, [...(groups.get(key) ?? []), { name: s.name, share, note: s.note }]);
  }
  const segmentCites = research.segments.flatMap((s) => s.cites);

  return (
    <div className="space-y-3">
      <Card title="What the company does">
        {research.business ? (
          <>
            <p className="text-[14px] leading-[21px]">{research.business.text}</p>
            <Cites cites={research.business.cites} />
          </>
        ) : (
          <p className="text-[13px] text-muted">Not available: the annual report could not be read for this company.</p>
        )}
      </Card>

      {(groups.size > 0 || plain.length > 0) && (
        <Card title="Revenue mix">
          <div className="space-y-4">
            {[...groups.entries()].map(([name, rows]) => (
              <div key={name}>
                {groups.size > 1 && <p className="mb-1.5 text-[12px] font-medium capitalize text-muted">By {name}</p>}
                <RankedBars rows={[...rows].sort((a, b) => b.share - a.share)} />
              </div>
            ))}
            {plain.length > 0 && (
              <ul className="space-y-1 text-[13px]">
                {plain.map((s) => <li key={s.name}>{s.name}{s.note ? <span className="text-muted"> · {s.note}</span> : null}</li>)}
              </ul>
            )}
          </div>
          <Cites cites={segmentCites} />
        </Card>
      )}

      <Card title={`Headline numbers · ${f.basis.toLowerCase()}`}>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3">
          {f.headline.map((h) => (
            <div key={h.label}>
              <dt className="text-[12px] text-muted">{h.label}</dt>
              <dd className="text-[17px] font-semibold leading-6 tracking-tight">{statValue(h)}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-[11px] leading-4 text-faint">
          From <a href={f.source_url} target="_blank" rel="noreferrer" className="underline">{f.source}</a>, which
          standardises the company&apos;s own filings.
        </p>
      </Card>

      <Card title="Sources read">
        <ul className="space-y-1.5">
          {research.docs.map((d) => (
            <li key={d.id} className="flex items-baseline gap-2 text-[13px]">
              <a href={d.url} target="_blank" rel="noreferrer" className="min-w-0 truncate text-accent">{d.label}</a>
              <span className="num ml-auto shrink-0 text-[11px] text-faint">
                {d.problem ? "not readable" : `${d.pages ?? "?"} pages`}
              </span>
            </li>
          ))}
        </ul>
        {research.warnings.map((w) => <p key={w} className="mt-2 text-[12px] leading-4 text-warn">{w}</p>)}
      </Card>
    </div>
  );
}

function Observations({ f, match }: { f: Financials; match: RegExp }) {
  const lines = f.observations.filter((o) => match.test(o));
  if (lines.length === 0) return null;
  return (
    <ul className="space-y-1.5 border-l-2 border-accent pl-3">
      {lines.map((o) => <li key={o} className="text-[14px] leading-[20px]">{o}</li>)}
    </ul>
  );
}

export function TrajectoryTab({ research }: { research: Research }) {
  const f = research.financials;
  const a = f.annual;
  const q = f.quarterly;
  const points = (labels: string[], values: (number | null)[]) => labels.map((label, i) => ({ label, value: values[i] }));
  const quarterLabels = q.periods.map((p) => p.replace(" FY", "'"));
  return (
    <div className="space-y-3">
      <Observations f={f} match={/Revenue growth|EBITDA margin|H1 |9M |1Q /} />
      <Card title="Year by year">
        <div className="space-y-4">
          <ColumnChart title="Revenue" points={points(a.years, a.revenue)} format={cr} />
          {!f.lender && <LineChart title="EBITDA margin" points={points(a.years, a.ebitda_margin)} format={(v) => pctText(v)} />}
          <ColumnChart title="PAT" points={points(a.years, a.pat)} format={cr} />
        </div>
        <div className="mt-3">
          <Table head={["Year", "Revenue", "Growth", ...(f.lender ? [] : ["EBITDA %"]), "PAT", "PAT growth"]}
            rows={a.years.map((y, i) => [y, a.revenue[i] === null ? null : amount(a.revenue[i]), signed(a.revenue_growth[i]),
              ...(f.lender ? [] : [pctText(a.ebitda_margin[i])]), a.pat[i] === null ? null : amount(a.pat[i]), signed(a.pat_growth[i])])} />
        </div>
      </Card>

      <Card title="Quarter by quarter">
        <ColumnChart title="Revenue growth, YoY" points={points(quarterLabels, q.revenue_yoy)} format={signed} height={80} />
        <div className="mt-3">
          <Table head={["Quarter", "Revenue", "YoY", ...(f.lender ? [] : ["EBITDA %"]), "PAT YoY"]}
            rows={q.periods.map((p, i) => [p, q.revenue[i] === null ? null : amount(q.revenue[i]), signed(q.revenue_yoy[i]),
              ...(f.lender ? [] : [pctText(q.ebitda_margin[i])]), signed(q.pat_yoy[i])]).slice(-6)} />
        </div>
      </Card>

      <Card title="Cash quality: do profits turn into cash?">
        <Observations f={f} match={/Operating cash flow/} />
        <div className="mt-3">
          <LineChart title="Operating cash flow as % of PAT" points={points(f.cash.years, f.cash.conversion)}
            format={(v) => pctText(v, 0)} reference={{ value: 100, label: "100% = every rupee of profit arrived as cash" }} />
        </div>
        <div className="mt-3">
          <Table head={["Year", "Op. cash flow", "PAT", "CFO / PAT", "Free cash flow"]}
            rows={f.cash.years.map((y, i) => [y, f.cash.cfo[i] === null ? null : amount(f.cash.cfo[i]),
              f.cash.pat[i] === null ? null : amount(f.cash.pat[i]), pctText(f.cash.conversion[i], 0),
              f.cash.fcf[i] === null ? null : amount(f.cash.fcf[i])])} />
        </div>
      </Card>
      <p className="text-[11px] text-faint">All figures {f.unit}, {f.basis.toLowerCase()}, computed from {f.source}.</p>
    </div>
  );
}

export function BalanceTab({ research }: { research: Research }) {
  const f = research.financials;
  const b = f.balance;
  const wc = b.working_capital;
  const days = (v: number | null) => (v === null ? null : v.toFixed(0));
  return (
    <div className="space-y-3">
      <Observations f={f} match={/Debt-to-equity|Debtor days/} />
      <Card title="Debt and leverage">
        <LineChart title="Debt to equity" points={b.periods.map((p, i) => ({ label: p, value: b.debt_equity[i] }))}
          format={(v) => `${v.toFixed(2)}x`} />
        <div className="mt-3">
          <Table head={["Period", "Borrowings", "Equity", "D/E"]}
            rows={b.periods.map((p, i) => [p, b.borrowings[i] === null ? null : amount(b.borrowings[i]),
              b.equity[i] === null ? null : amount(b.equity[i]), b.debt_equity[i] === null ? null : `${b.debt_equity[i]!.toFixed(2)}x`])} />
        </div>
      </Card>
      <Card title="Working capital cycle and returns">
        <Table head={["Year", "Debtor days", "Inventory", "Payable", "Cash cycle", "ROCE"]}
          rows={wc.years.map((y, i) => [y, days(wc.debtor_days[i]), days(wc.inventory_days[i]), days(wc.payable_days[i]),
            days(wc.cash_conversion_cycle[i]), wc.roce[i] === null ? null : `${wc.roce[i]!.toFixed(0)}%`])} />
        <p className="mt-2 text-[11px] leading-4 text-faint">
          Days of sales tied up in receivables and inventory, less days of credit from suppliers. A lengthening cycle
          drains cash.
        </p>
      </Card>
      <p className="text-[11px] text-faint">All figures {f.unit}, {f.basis.toLowerCase()}, computed from {f.source}.</p>
    </div>
  );
}

function Side({ title, tone, points }: { title: string; tone: string; points: Research["bull"] }) {
  return (
    <Card>
      <h2 className={`text-[13px] font-semibold ${tone}`}>{title}</h2>
      {points.length === 0 ? (
        <p className="mt-2 text-[13px] text-muted">No point survived the citation check.</p>
      ) : (
        <ol className="mt-2 space-y-3">
          {points.map((p) => (
            <li key={p.point}>
              <p className="text-[14px] leading-[21px]">{p.point}</p>
              <Cites cites={p.cites} />
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function CaseTab({ research }: { research: Research }) {
  return (
    <div className="space-y-3">
      <Side title="Bull case" tone="text-up" points={research.bull} />
      <Side title="Bear case" tone="text-down" points={research.bear} />
      <p className="text-[11px] leading-4 text-faint">
        Written only from the company&apos;s annual report, its concall transcripts and figures computed from its
        reported financials. A point with no source is not shown.
      </p>
    </div>
  );
}

const SUGGESTED = [
  "What margin has management guided, and what has it delivered?",
  "What risks does management itself flag?",
  "What is the capex plan and how is it funded?",
  "How concentrated is revenue in top customers?",
];

export function AskTab({ research }: { research: Research }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Answer[]>([]);

  async function submit(text: string) {
    const q = text.trim();
    if (q.length < 3 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const a = await ask(research.symbol, q);
      setAnswers((prev) => [a, ...prev]);
      setQuestion("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (!hasBackend) {
    return (
      <p className="rounded-xl border border-dashed border-line px-4 py-8 text-center text-[13px] leading-5 text-muted">
        Ask FINN answers from the filings on a server, which this build is not connected to. The other tabs work without it.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <form onSubmit={(e) => { e.preventDefault(); void submit(question); }}
        className="flex items-center gap-2 rounded-xl border border-line bg-surface pl-3 pr-1.5">
        <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={400}
          placeholder={`Ask about ${research.symbol}`} aria-label={`Ask a question about ${research.name}`}
          className="h-12 min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-faint" />
        <button type="submit" disabled={busy || question.trim().length < 3} aria-label="Ask"
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink text-bg disabled:opacity-30">
          <SendIcon width={18} height={18} />
        </button>
      </form>
      <p className="text-[11px] leading-4 text-faint">
        Answers come only from this company&apos;s annual report and concall transcripts. If they don&apos;t say it, FINN says so.
      </p>

      {answers.length === 0 && !busy && (
        <ul className="space-y-1.5">
          {SUGGESTED.map((s) => (
            <li key={s}>
              <button type="button" onClick={() => void submit(s)}
                className="min-h-10 w-full rounded-lg border border-line bg-surface px-3 py-2 text-left text-[13px] text-muted">{s}</button>
            </li>
          ))}
        </ul>
      )}

      {busy && (
        <div className="rounded-xl border border-line bg-surface p-3.5" aria-busy="true">
          <p className="text-[13px] text-muted">Reading the filings…</p>
          <div className="skeleton mt-2 h-3 w-full" />
          <div className="skeleton mt-2 h-3 w-2/3" />
        </div>
      )}
      {error && <p role="alert" className="rounded-lg bg-sunken px-3 py-2 text-[13px] text-warn">{error}</p>}

      {answers.map((a, i) => (
        <article key={`${a.question}-${answers.length - i}`} className="rounded-xl border border-line bg-surface p-3.5">
          <h3 className="text-[13px] font-medium text-muted">{a.question}</h3>
          {a.not_disclosed ? (
            <p className="mt-2 text-[14px] leading-[21px]">Not disclosed in the sources.</p>
          ) : (
            <ul className="mt-2 space-y-2.5">
              {a.sentences.map((s) => (
                <li key={s.text}>
                  <p className="text-[14px] leading-[21px]">{s.text}</p>
                  <Cites cites={s.cites} />
                </li>
              ))}
            </ul>
          )}
        </article>
      ))}
    </div>
  );
}
