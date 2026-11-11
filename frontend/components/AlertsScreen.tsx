"use client";

import { useMemo } from "react";
import { firedAlerts, type FiredAlert } from "@/lib/brief";
import { CATEGORY_LABEL, dayLabel, direction, istDay, pct, price, volume } from "@/lib/format";
import { usePrefs } from "@/lib/store";
import type { Announcement, Snapshot } from "@/lib/types";
import { LinkIcon } from "./icons";
import { DataStamp, PageTitle, WithSnapshot } from "./Shell";
import { Thresholds } from "./Thresholds";

const LOOKBACK_DAYS = 7;

/** What crossed, by how much, against what baseline. */
function MarketAlert({ a }: { a: FiredAlert }) {
  const d = a.day;
  if (a.type === "price") {
    return (
      <li className="card p-3.5">
        <div className="flex items-baseline gap-2">
          <span className="tick text-[15px] font-semibold">{a.symbol}</span>
          <span className="label">Price move</span>
          <span className="num ml-auto text-[11px] text-faint">{dayLabel(a.date)}</span>
        </div>
        <p className={`num mt-1 text-[24px] font-semibold leading-7 ${direction(a.value)}`}>{pct(a.value, 2)}</p>
        <p className="num mt-1 text-[12px] text-muted">
          ₹{price(d.prev_close)} → ₹{price(d.close)} · your threshold ±{a.threshold.toFixed(1)}% ·{" "}
          {(Math.abs(a.value) / a.threshold).toFixed(1)}x over
        </p>
      </li>
    );
  }
  const fill = Math.min(100, (100 * (d.avg_vol_20 ?? 0)) / d.volume);
  return (
    <li className="card p-3.5">
      <div className="flex items-baseline gap-2">
        <span className="tick text-[15px] font-semibold">{a.symbol}</span>
        <span className="label">Volume</span>
        <span className="num ml-auto text-[11px] text-faint">{dayLabel(a.date)}</span>
      </div>
      <p className="num mt-1 text-[24px] font-semibold leading-7">{a.value.toFixed(1)}x <span className="text-[13px] font-normal text-muted">its 20-day average</span></p>
      <div className="mt-2 h-1.5 rounded-full bg-accent" role="img"
        aria-label={`Traded ${volume(d.volume)} against an average of ${volume(d.avg_vol_20)}`}>
        <div className="h-1.5 rounded-full bg-faint" style={{ width: `${fill}%` }} />
      </div>
      <p className="num mt-1.5 text-[12px] text-muted">
        {volume(d.volume)} traded vs {volume(d.avg_vol_20)} average · your threshold {a.threshold.toFixed(1)}x · price{" "}
        <span className={direction(d.pct_change)}>{pct(d.pct_change)}</span>
      </p>
    </li>
  );
}

function FilingAlert({ a }: { a: Announcement }) {
  return (
    <li className="flex items-start gap-3 border-b border-line py-2.5 last:border-0">
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline gap-2">
          <span className="tick text-[13px] font-semibold">{a.symbol}</span>
          <span className="label">{CATEGORY_LABEL[a.category]}</span>
          <span className="num ml-auto text-[11px] text-faint">{dayLabel(a.ts)}</span>
        </p>
        <p className="mt-0.5 line-clamp-2 text-[13px] leading-[18px] text-muted">
          {a.summary ?? (a.category === "results" && a.period ? `${a.period} results` : a.title)}
        </p>
      </div>
      {a.url && (
        <a href={a.url} target="_blank" rel="noreferrer" aria-label="Open the filing" className="mt-4 text-accent">
          <LinkIcon width={16} height={16} />
        </a>
      )}
    </li>
  );
}

function Ready({ snap, source, refreshing }: { snap: Snapshot; source: string; refreshing: boolean }) {
  const { settings, mutes } = usePrefs();
  const end = new Date(snap.as_of.announcements ?? snap.generated_at);
  const start = new Date(end.getTime() - LOOKBACK_DAYS * 86400_000);
  const market = useMemo(
    () => firedAlerts(snap, settings, istDay(start.toISOString()), istDay(end.toISOString())),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [snap, settings],
  );
  const filings = snap.announcements.filter((a) =>
    settings.alert_categories.includes(a.category) && a.score >= snap.material_threshold &&
    !mutes[`${a.symbol}|${a.category}`] &&
    new Date(a.ts) >= start && new Date(a.ts) <= end);

  return (
    <>
      <PageTitle title="Alerts" sub={`Last ${LOOKBACK_DAYS} days. You decide what unusual means.`} />
      <section className="card p-3.5">
        <Thresholds />
      </section>

      <h2 className="label mt-5">Market moves · {market.length}</h2>
      {market.length > 0 ? (
        <ul className="mt-1.5 space-y-3">{market.map((a) => <MarketAlert key={a.id} a={a} />)}</ul>
      ) : (
        <p className="mt-1.5 rounded-[18px] border border-dashed border-line px-4 py-6 text-center text-[13px] text-muted">
          Nothing crossed {settings.volume_multiple.toFixed(1)}x volume or ±{settings.price_move_pct.toFixed(1)}% in the last {LOOKBACK_DAYS} days.
          Lower a threshold to see more.
        </p>
      )}

      <h2 className="label mt-5">Filings in types you follow · {filings.length}</h2>
      {filings.length > 0 ? (
        <ul className="mt-1.5 card px-3.5">{filings.map((a) => <FilingAlert key={a.id} a={a} />)}</ul>
      ) : (
        <p className="mt-1.5 rounded-[18px] border border-dashed border-line px-4 py-6 text-center text-[13px] text-muted">
          No filings in your followed types this week. Choose types in Settings.
        </p>
      )}
      <div className="mt-5"><DataStamp snap={snap} source={source} refreshing={refreshing} /></div>
    </>
  );
}

export function AlertsScreen() {
  return <WithSnapshot>{(snap, meta) => <Ready snap={snap} {...meta} />}</WithSnapshot>;
}
