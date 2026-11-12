"use client";

import { CATEGORY_LABEL } from "@/lib/format";
import { setSettings, update, usePrefs, type Theme } from "@/lib/store";
import type { Category, Snapshot } from "@/lib/types";
import { DataStamp, PageTitle, WithSnapshot } from "./Shell";
import { Thresholds } from "./Thresholds";

const ALERTABLE: Category[] = [
  "results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "credit_rating",
  "dividend", "bonus_split", "capex", "insider_trading", "press_release",
];
const THEMES: { key: Theme; label: string }[] = [
  { key: "system", label: "System" }, { key: "light", label: "Light" }, { key: "dark", label: "Dark" },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h2 className="label">{title}</h2>
      <div className="mt-1.5 card p-3.5">{children}</div>
    </section>
  );
}

function Ready({ snap, source, refreshing, liveError }: {
  snap: Snapshot; source: string; refreshing: boolean; liveError?: string | null;
}) {
  const prefs = usePrefs();
  const followed = prefs.settings.alert_categories;
  const mutes = Object.keys(prefs.mutes);
  const triaged = Object.keys(prefs.seen).length + Object.keys(prefs.starred).length;

  const toggleCategory = (c: Category) =>
    setSettings({ alert_categories: followed.includes(c) ? followed.filter((x) => x !== c) : [...followed, c] });

  return (
    <>
      <PageTitle title="Settings" sub="Saved on this device. No account needed." />

      <Section title="Market alert thresholds"><Thresholds /></Section>

      <Section title="Alert me on these filing types">
        <div className="flex flex-wrap gap-1.5">
          {ALERTABLE.map((c) => {
            const on = followed.includes(c);
            return (
              <button key={c} type="button" aria-pressed={on} onClick={() => toggleCategory(c)}
                className={`h-9 rounded-full border px-3 text-[13px] font-medium ${
                  on ? "border-accent bg-accent-soft text-accent" : "border-line text-muted"}`}>
                {CATEGORY_LABEL[c]}
              </button>
            );
          })}
        </div>
      </Section>

      <Section title={`Muted · ${mutes.length}`}>
        {mutes.length === 0 ? (
          <p className="text-[13px] text-muted">
            Nothing muted. Use “Mute” on a card to bury that filing type for that company.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {mutes.map((key) => {
              const [symbol, category] = key.split("|") as [string, Category];
              return (
                <li key={key} className="flex h-11 items-center text-[13px]">
                  <span className="tick font-semibold">{symbol}</span>
                  <span className="ml-2 text-muted">{CATEGORY_LABEL[category]}</span>
                  <button type="button" className="ml-auto h-9 px-2 font-medium text-accent"
                    onClick={() => update((p) => {
                      const next = { ...p.mutes };
                      delete next[key];
                      return { mutes: next };
                    })}>
                    Unmute
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      <Section title="Appearance">
        <div role="group" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-lg bg-sunken p-1">
          {THEMES.map(({ key, label }) => (
            <button key={key} type="button" aria-pressed={prefs.theme === key} onClick={() => update({ theme: key })}
              className={`h-9 rounded-md text-[13px] font-medium ${prefs.theme === key ? "bg-surface text-ink shadow-sm" : "text-muted"}`}>
              {label}
            </button>
          ))}
        </div>
      </Section>

      <Section title="Data">
        <p className="text-[13px] text-muted">
          {snap.portfolio.length} companies · {snap.announcements.length} filings stored · last session {snap.as_of.last_session}
        </p>
        <div className="mt-1"><DataStamp snap={snap} source={source} refreshing={refreshing} liveError={liveError} /></div>
        <button type="button" disabled={triaged === 0} onClick={() => update({ seen: {}, starred: {} })}
          className="mt-3 h-10 rounded-md border border-line px-3 text-[13px] font-medium disabled:opacity-40">
          Clear seen and starred ({triaged})
        </button>
      </Section>
    </>
  );
}

export function SettingsScreen() {
  return <WithSnapshot>{(snap, meta) => <Ready snap={snap} {...meta} />}</WithSnapshot>;
}
