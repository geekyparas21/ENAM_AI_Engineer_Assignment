export type Category =
  | "results" | "M&A" | "fund_raise" | "management_change" | "litigation" | "insider_trading"
  | "earnings_call" | "investor_meetings" | "credit_rating" | "dividend" | "bonus_split" | "capex"
  | "press_release" | "postal_ballot" | "agm_egm" | "pledging" | "unclassified";

export interface MarketDay {
  symbol: string;
  date: string;
  close: number;
  prev_close: number | null;
  pct_change: number | null;
  volume: number;
  avg_vol_20: number | null;
  vol_ratio: number | null;
}

export interface Holding {
  symbol: string;
  company: string;
  sector: string;
  date: string | null;
  close: number | null;
  pct_change: number | null;
  volume: number | null;
  avg_vol_20: number | null;
  vol_ratio: number | null;
  spark: number[];
}

export interface Metric {
  cur: number | null;
  prev: number | null;
  yoy: number | null;
  qoq_pct: number | null;
  yoy_pct: number | null;
}

export interface ResultsDetail {
  type: "results";
  basis: string;            // Consolidated | Standalone
  unit: string;             // e.g. "Rs crore"
  period: string | null;
  metrics: { revenue: Metric; ebitda: Metric; pbt: Metric; pat: Metric };
  margins: { ebitda: Metric; pat: Metric };   // values in %, deltas in percentage points
  ebitda_definition: string;
  checks: { name: string; ok: boolean; note: string }[];
  page: number | null;
  source: "filing" | "screener";
  source_note: string;
}

export interface PeopleDetail {
  type: "people";
  people: {
    name: string;
    role: string;
    action: string;         // appointed | resigned | retired | ceased
    effective: string | null;
    bio: string | null;
    bio_source: string | null;
    bio_url: string | null;
  }[];
}

export type Detail = ResultsDetail | PeopleDetail;

export interface Announcement {
  id: string;
  symbol: string;
  company: string;
  ts: string;
  exch_category: string;
  subject: string;
  title: string;
  period: string | null;
  url: string | null;
  source: string;
  category: Category;
  kind: string | null;
  method: string | null;
  score: number;
  reasons: string[];
  move: { date: string; pct_change: number | null; vol_ratio: number | null } | null;
  summary: string | null;
  detail: Detail | null;
}

export interface Settings {
  volume_multiple: number;
  price_move_pct: number;
  alert_categories: Category[];
}

export interface Snapshot {
  generated_at: string;
  as_of: { prices: string | null; announcements: string | null; last_session: string | null };
  material_threshold: number;
  defaults: Settings;
  portfolio: Holding[];
  market: Record<string, MarketDay[]>;
  announcements: Announcement[];
  stats?: {
    calls: number;
    cached: number;
    tokens: number;
    cost_usd: number | null;   // null when a model's price is not configured: never invented
    cost_inr: number | null;
    usd_inr: number | null;
    by_task: {
      task: string; tier: string; model: string; calls: number; cached: number;
      prompt_tokens: number; completion_tokens: number; cost_usd: number | null;
    }[];
  } | null;
}
