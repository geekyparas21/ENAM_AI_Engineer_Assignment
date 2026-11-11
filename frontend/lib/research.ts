"use client";

import { apiBase } from "./data";

export type Verdict =
  | "delivered" | "missed" | "moved_goalposts" | "quietly_dropped" | "in_progress" | "unverifiable";

export interface Cite {
  id?: string;
  kind: "page" | "fact";
  label: string;
  page?: number | null;
  url?: string | null;
  text?: string;
}

export interface PromiseThread {
  id: string;
  title: string;
  metric: string;
  period: string | null;
  verdict: Verdict;
  progress: "ahead" | "on_track" | "behind" | null;
  checked_by_code: boolean;
  basis: string;
  initial_target: string | null;
  target: { text: string | null; low: number | null; high: number | null; unit: string | null; direction: string };
  evidence: string;
  delivered: { key: string; label: string; text: string; value: number; unit: string; partial: boolean; on_period: boolean }[];
  history: {
    call: string; call_label: string; when: string | null; target: string | null; status: string | null;
    speaker: string | null; quote: string; page: number; url: string;
  }[];
}

export interface Financials {
  basis: string;
  unit: string;
  source: string;
  source_url: string;
  lender: boolean;
  headline: { label: string; value: number; unit: string }[];
  annual: {
    years: string[]; revenue: (number | null)[]; revenue_growth: (number | null)[];
    ebitda: (number | null)[]; ebitda_margin: (number | null)[]; pat: (number | null)[];
    pat_growth: (number | null)[]; pat_margin: (number | null)[];
  };
  quarterly: {
    periods: string[]; revenue: (number | null)[]; revenue_yoy: (number | null)[];
    ebitda_margin: (number | null)[]; pat: (number | null)[]; pat_yoy: (number | null)[];
  };
  ytd: { label: string; revenue_growth: number | null; ebitda_margin: number | null; pat_growth: number | null } | null;
  cash: {
    years: string[]; cfo: (number | null)[]; pat: (number | null)[]; conversion: (number | null)[];
    fcf: (number | null)[];
  };
  balance: {
    periods: string[]; borrowings: (number | null)[]; equity: (number | null)[]; debt_equity: (number | null)[];
    working_capital: {
      years: string[]; debtor_days: (number | null)[]; inventory_days: (number | null)[];
      payable_days: (number | null)[]; cash_conversion_cycle: (number | null)[]; roce: (number | null)[];
    };
  };
  observations: string[];
}

export interface Research {
  symbol: string;
  name: string;
  generated_at: string;
  docs: { id: string; kind: string; label: string; short: string; url: string; pages: number | null; problem: string | null }[];
  financials: Financials;
  promises: {
    calls: { id: string; label: string; short: string; url: string }[];
    threads: PromiseThread[];
    scorecard: { counts: Record<Verdict, number>; total: number; settled: number; kept_pct: number | null };
    statements_found: number;
    statements_unverified: number;
  };
  business: { text: string; cites: Cite[] } | null;
  segments: { name: string; share: string | null; note: string | null; cites: Cite[] }[];
  bull: { point: string; cites: Cite[] }[];
  bear: { point: string; cites: Cite[] }[];
  warnings: string[];
  usage: { calls: number; cached: number; tokens: number; cost_usd: number | null };
}

export interface IndexEntry {
  symbol: string;
  name: string;
  generated_at: string;
  threads: number;
  kept_pct: number | null;
}

export interface Answer {
  question: string;
  not_disclosed: boolean;
  sentences: { text: string; cites: Cite[] }[];
}

export const hasBackend = Boolean(apiBase);

async function getJson<T>(url: string, timeoutMs = 20000): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/** Companies already researched: the ones shipped with the app, plus any the backend has built since. */
export async function loadIndex(): Promise<IndexEntry[]> {
  const shipped = (await getJson<IndexEntry[]>("/research/index.json")) ?? [];
  const merged = new Map(shipped.map((e) => [e.symbol, e]));
  if (hasBackend) {
    const live = await getJson<{ available: IndexEntry[] }>(`${apiBase}/api/research`, 8000);
    for (const e of live?.available ?? []) if (!merged.has(e.symbol)) merged.set(e.symbol, e);
  }
  return [...merged.values()];
}

/** Shipped file first (instant, no backend), then the backend's copy. null = not researched yet. */
export async function loadResearch(symbol: string): Promise<Research | null> {
  const shipped = await getJson<Research>(`/research/${encodeURIComponent(symbol)}.json`);
  if (shipped) return shipped;
  if (!hasBackend) return null;
  return getJson<Research>(`${apiBase}/api/research/${encodeURIComponent(symbol)}`, 60000);
}

export interface BuildProgress {
  message: string;
  step: number;
  steps: number;
}

/** Research a new ticker on the backend, reporting progress as it reads each document. */
export function buildResearch(
  symbol: string,
  onProgress: (p: BuildProgress) => void,
): { done: Promise<void>; cancel: () => void } {
  let source: EventSource | null = null;
  const done = new Promise<void>((resolve, reject) => {
    if (!hasBackend) {
      reject(new Error("The research engine is not connected."));
      return;
    }
    source = new EventSource(`${apiBase}/api/research/${encodeURIComponent(symbol)}/build`);
    source.onmessage = (event) => {
      const data = JSON.parse(event.data) as { type: string; message?: string; step?: number; steps?: number };
      if (data.type === "progress") {
        onProgress({ message: data.message ?? "", step: data.step ?? 0, steps: data.steps ?? 5 });
      } else if (data.type === "done") {
        source?.close();
        resolve();
      } else if (data.type === "error") {
        source?.close();
        reject(new Error(data.message ?? "Research failed."));
      }
    };
    source.onerror = () => {
      source?.close();
      reject(new Error("Lost the connection to the research engine. It may be waking up; try again in a minute."));
    };
  });
  return { done, cancel: () => source?.close() };
}

export async function ask(symbol: string, question: string): Promise<Answer> {
  if (!hasBackend) throw new Error("Ask FINN needs the research engine, which is not connected.");
  const res = await fetch(`${apiBase}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, question }),
  });
  if (!res.ok) {
    const detail = await res.json().then((d) => d.detail as string).catch(() => null);
    throw new Error(detail ?? `The research engine returned an error (${res.status}).`);
  }
  return (await res.json()) as Answer;
}

/** Wake a sleeping free-tier backend as soon as the Research tab opens. */
export function wakeBackend(): void {
  if (hasBackend) void fetch(`${apiBase}/api/health`, { cache: "no-store" }).catch(() => undefined);
}
