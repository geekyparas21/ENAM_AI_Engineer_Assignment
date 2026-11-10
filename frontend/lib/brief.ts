import { CATEGORY_LABEL, istDay, pct } from "./format";
import { muteKey, type Prefs, type WindowKey } from "./store";
import type { Announcement, Category, MarketDay, Settings, Snapshot } from "./types";

const HOURS: Record<Exclude<WindowKey, "custom">, number> = { "24h": 24, "3d": 72, "7d": 168, "30d": 720 };

export interface Range {
  start: Date;
  end: Date;
}

/**
 * The window ends at the last successful data fetch, not at the wall clock. If
 * ingestion is behind, "last 24h" still means the latest 24h we actually have,
 * and the header says so.
 */
export function windowRange(snap: Snapshot, prefs: Prefs): Range {
  const anchor = new Date(snap.as_of.announcements ?? snap.generated_at);
  if (prefs.window === "custom" && prefs.customFrom && prefs.customTo) {
    return {
      start: new Date(`${prefs.customFrom}T00:00:00+05:30`),
      end: new Date(`${prefs.customTo}T23:59:59+05:30`),
    };
  }
  const hours = HOURS[prefs.window === "custom" ? "24h" : prefs.window];
  return { start: new Date(anchor.getTime() - hours * 3600_000), end: anchor };
}

export interface Ranked extends Announcement {
  personalScore: number;
  personalReasons: string[];
  muted: boolean;
  starred: boolean;
  seen: boolean;
}

export interface Cluster {
  head: Ranked;
  related: Ranked[];
}

export interface Brief {
  range: Range;
  total: number;
  material: Cluster[];
  seen: Cluster[];
  routine: { category: Category; items: Ranked[] }[];
  routineCount: number;
}

/** Device-side modifiers: a mute sends that company+type to routine; a star lifts it. */
function personalise(a: Announcement, prefs: Prefs, starredPairs: Set<string>): Ranked {
  const key = muteKey(a.symbol, a.category);
  const muted = Boolean(prefs.mutes[key]);
  const starred = Boolean(prefs.starred[a.id]);
  let score = a.score;
  const reasons = [...a.reasons];
  if (muted) {
    score = 0;
    reasons.push(`You muted ${CATEGORY_LABEL[a.category].toLowerCase()} for ${a.symbol}`);
  } else if (starredPairs.has(key)) {
    score *= 1.2;
    reasons.push(`You starred ${CATEGORY_LABEL[a.category].toLowerCase()} from ${a.symbol} before (x1.2)`);
  }
  return {
    ...a, personalScore: score, personalReasons: reasons, muted, starred,
    seen: Boolean(prefs.seen[a.id]),
  };
}

export function buildBrief(snap: Snapshot, prefs: Prefs): Brief {
  const range = windowRange(snap, prefs);
  const byId = new Map(snap.announcements.map((a) => [a.id, a]));
  const starredPairs = new Set<string>();
  for (const id of Object.keys(prefs.starred)) {
    const a = byId.get(id);
    if (a) starredPairs.add(muteKey(a.symbol, a.category));
  }

  const inWindow = snap.announcements
    .filter((a) => {
      const t = new Date(a.ts).getTime();
      return t >= range.start.getTime() && t <= range.end.getTime();
    })
    .map((a) => personalise(a, prefs, starredPairs));

  const materialItems = inWindow.filter((a) => a.personalScore >= snap.material_threshold);
  const routineItems = inWindow.filter((a) => a.personalScore < snap.material_threshold);

  // One company often files several documents for the same event on the same day
  // (results, the deck, the board outcome). Show one card, tuck the rest behind it.
  const clusters = new Map<string, Cluster>();
  for (const a of [...materialItems].sort((x, y) => y.personalScore - x.personalScore || y.ts.localeCompare(x.ts))) {
    const key = `${a.symbol}|${a.category}|${istDay(a.ts)}`;
    const existing = clusters.get(key);
    if (existing) existing.related.push(a);
    else clusters.set(key, { head: a, related: [] });
  }
  const all = [...clusters.values()];
  const isSeen = (c: Cluster) => c.head.seen;

  const groups = new Map<Category, Ranked[]>();
  for (const a of routineItems) {
    const list = groups.get(a.category) ?? [];
    list.push(a);
    groups.set(a.category, list);
  }

  return {
    range,
    total: inWindow.length,
    material: all.filter((c) => !isSeen(c)),
    seen: all.filter(isSeen),
    routine: [...groups.entries()]
      .map(([category, items]) => ({ category, items }))
      .sort((a, b) => b.items.length - a.items.length),
    routineCount: routineItems.length,
  };
}

export interface FiredAlert {
  id: string;
  type: "price" | "volume";
  symbol: string;
  date: string;
  value: number;
  threshold: number;
  day: MarketDay;
}

/** Same comparison as backend/finn/alerts.py; ratios and baselines are computed in Python. */
export function firedAlerts(snap: Snapshot, settings: Settings, fromDay: string, toDay: string): FiredAlert[] {
  const out: FiredAlert[] = [];
  for (const days of Object.values(snap.market)) {
    for (const d of days) {
      if (d.date < fromDay || d.date > toDay) continue;
      if (d.pct_change !== null && Math.abs(d.pct_change) >= settings.price_move_pct) {
        out.push({ id: `p-${d.symbol}-${d.date}`, type: "price", symbol: d.symbol, date: d.date,
          value: d.pct_change, threshold: settings.price_move_pct, day: d });
      }
      if (d.vol_ratio !== null && d.vol_ratio >= settings.volume_multiple) {
        out.push({ id: `v-${d.symbol}-${d.date}`, type: "volume", symbol: d.symbol, date: d.date,
          value: d.vol_ratio, threshold: settings.volume_multiple, day: d });
      }
    }
  }
  return out.sort((a, b) => b.date.localeCompare(a.date) || Math.abs(b.value) - Math.abs(a.value));
}

/** The 2-3 line top summary. Composed from facts in code: no model call, nothing to hallucinate. */
export function headline(brief: Brief, snap: Snapshot): string[] {
  const lines: string[] = [];
  const heads = brief.material.map((c) => c.head);
  if (heads.length === 0) return lines;

  const byCat = new Map<Category, string[]>();
  for (const h of heads) {
    const list = byCat.get(h.category) ?? [];
    if (!list.includes(h.symbol)) list.push(h.symbol);
    byCat.set(h.category, list);
  }
  const names = (list: string[]) => (list.length <= 3 ? list.join(", ") : `${list.slice(0, 3).join(", ")} +${list.length - 3}`);
  const parts = [...byCat.entries()].slice(0, 3)
    .map(([cat, list]) => `${CATEGORY_LABEL[cat]}: ${names(list)}`);
  lines.push(`${parts.join(". ")}.`);

  const reacted = heads
    .filter((h) => h.move && h.move.pct_change !== null)
    .sort((a, b) => Math.abs(b.move!.pct_change!) - Math.abs(a.move!.pct_change!))[0];
  if (reacted?.move) {
    const vol = reacted.move.vol_ratio && reacted.move.vol_ratio >= 2 ? ` on ${reacted.move.vol_ratio.toFixed(1)}x volume` : "";
    lines.push(`Sharpest reaction: ${reacted.symbol} ${pct(reacted.move.pct_change)}${vol} after its ${CATEGORY_LABEL[reacted.category].toLowerCase()} filing.`);
  }
  void snap;
  return lines;
}

/** When the chosen window is empty, the smallest preset window that has something material. */
export function nearestBusyWindow(snap: Snapshot, prefs: Prefs): WindowKey | null {
  for (const key of ["3d", "7d", "30d"] as const) {
    const b = buildBrief(snap, { ...prefs, window: key });
    if (b.material.length + b.seen.length > 0) return key;
  }
  return null;
}
