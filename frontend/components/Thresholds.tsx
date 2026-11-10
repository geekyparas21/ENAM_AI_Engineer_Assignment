"use client";

import { setSettings, usePrefs } from "@/lib/store";

function Slider({ label, value, min, max, step, format, onChange }: {
  label: string; value: number; min: number; max: number; step: number;
  format: (v: number) => string; onChange: (v: number) => void;
}) {
  const id = label.replace(/\W+/g, "-").toLowerCase();
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-[13px] text-muted">{label}</label>
        <output htmlFor={id} className="num text-[15px] font-semibold">{format(value)}</output>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} className="mt-1 h-8 w-full" />
    </div>
  );
}

/** "I decide what unusual means": the two market thresholds, used on Alerts and Settings. */
export function Thresholds() {
  const { settings } = usePrefs();
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Slider label="Volume above 20-day average" value={settings.volume_multiple} min={1.2} max={6} step={0.1}
        format={(v) => `${v.toFixed(1)}x`} onChange={(v) => setSettings({ volume_multiple: v })} />
      <Slider label="Daily price move beyond" value={settings.price_move_pct} min={1} max={15} step={0.5}
        format={(v) => `±${v.toFixed(1)}%`} onChange={(v) => setSettings({ price_move_pct: v })} />
    </div>
  );
}
