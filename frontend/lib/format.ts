import type { Category } from "./types";

const IST = "Asia/Kolkata";

export const CATEGORY_LABEL: Record<Category, string> = {
  results: "Results",
  "M&A": "M&A",
  fund_raise: "Fund raise",
  management_change: "Management",
  litigation: "Legal & regulatory",
  insider_trading: "Insider trade",
  earnings_call: "Earnings call",
  investor_meetings: "Investor meetings",
  credit_rating: "Credit rating",
  dividend: "Dividend",
  bonus_split: "Bonus / split",
  capex: "Capex",
  press_release: "Press release",
  postal_ballot: "Postal ballot",
  agm_egm: "AGM / EGM",
  pledging: "Pledging",
  unclassified: "Compliance paperwork",
};

/** "Titan Company Limited" -> "Titan Company": how a person would say it. */
export function shortName(company: string | null | undefined, fallback: string): string {
  const name = (company ?? "").replace(/\s+(Limited|Ltd\.?)$/i, "").replace(/\s*\(India\)/i, "").trim();
  return name || fallback;
}

export function greeting(now: Date): string {
  const hour = now.getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}%`;
}

export function direction(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-muted";
  return value > 0 ? "text-up" : "text-down";
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Indian-style compact volume: 12.4L, 1.97Cr. */
export function volume(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  if (value >= 1e7) return `${(value / 1e7).toFixed(2)}Cr`;
  if (value >= 1e5) return `${(value / 1e5).toFixed(1)}L`;
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`;
  return String(Math.round(value));
}

export function amount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 0 : abs >= 100 ? 1 : 2;
  const text = abs.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return value < 0 ? `−${text}` : text;
}

export function dateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: IST, day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(iso));
}

export function dayLabel(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { timeZone: IST, day: "numeric", month: "short" })
    .format(new Date(iso.length === 10 ? `${iso}T12:00:00+05:30` : iso));
}

/** Calendar day in IST, as YYYY-MM-DD. */
export function istDay(iso: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: IST }).format(new Date(iso));
}

export function ago(iso: string, now: Date): string {
  const mins = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return dayLabel(iso);
}
