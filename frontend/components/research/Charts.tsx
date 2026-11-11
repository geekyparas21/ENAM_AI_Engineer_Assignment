"use client";

import { useState } from "react";

/**
 * Chart primitives for the research tabs. One series, one hue (--chart), one axis.
 * Marks are thin; text uses text tokens, never the series colour. Every chart has a
 * readout that shows the latest value by default and the touched or focused mark
 * otherwise, and every chart sits above a table that carries all of its values.
 */

type Point = { label: string; value: number | null };

function useActive(points: Point[]) {
  const lastIndex = points.reduce((acc, p, i) => (p.value !== null ? i : acc), -1);
  const [active, setActive] = useState<number | null>(null);
  const shown = active !== null && points[active]?.value !== null ? active : lastIndex;
  return { shown, setActive, lastIndex };
}

function Readout({ title, label, value }: { title: string; label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h3 className="text-[13px] font-medium">{title}</h3>
      <p className="num text-[12px] text-muted" aria-live="polite">
        {label} <span className="ml-1 text-[13px] font-semibold text-ink">{value}</span>
      </p>
    </div>
  );
}

const W = 320;
const PAD_X = 6;

/** Columns from a zero baseline: magnitude over time. Negative values grow downward. */
export function ColumnChart({ title, points, format, height = 96 }: {
  title: string; points: Point[]; format: (v: number) => string; height?: number;
}) {
  const { shown, setActive } = useActive(points);
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  if (values.length === 0) return null;
  const max = Math.max(0, ...values);
  const min = Math.min(0, ...values);
  const span = max - min || 1;
  const top = 6;
  const plot = height - top - 4;
  const y = (v: number) => top + ((max - v) / span) * plot;
  const band = (W - PAD_X * 2) / points.length;
  const bar = Math.min(24, band - 2);
  const zero = y(0);

  return (
    <figure>
      <Readout title={title} label={points[shown]?.label ?? ""} value={shown >= 0 ? format(points[shown].value as number) : "–"} />
      <svg viewBox={`0 0 ${W} ${height + 16}`} className="mt-1 w-full" role="img"
        aria-label={`${title}: ${points.filter((p) => p.value !== null).map((p) => `${p.label} ${format(p.value as number)}`).join(", ")}`}>
        <line x1={PAD_X} x2={W - PAD_X} y1={zero} y2={zero} stroke="var(--line)" strokeWidth="1" />
        {points.map((p, i) => {
          const cx = PAD_X + band * i + band / 2;
          const v = p.value;
          const h = v === null ? 0 : Math.abs(y(v) - zero);
          const up = v === null || v >= 0;
          const x0 = cx - bar / 2;
          const yTop = up ? zero - h : zero;
          const r = Math.min(4, h);
          // Rounded at the data end, square at the baseline.
          const path = up
            ? `M${x0},${zero} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x0 + bar - r} Q${x0 + bar},${yTop} ${x0 + bar},${yTop + r} V${zero} Z`
            : `M${x0},${zero} V${zero + h - r} Q${x0},${zero + h} ${x0 + r},${zero + h} H${x0 + bar - r} Q${x0 + bar},${zero + h} ${x0 + bar},${zero + h - r} V${zero} Z`;
          return (
            <g key={p.label}>
              {v !== null && h > 0 && <path d={path} fill="var(--chart)" opacity={i === shown ? 1 : 0.55} />}
              <text x={cx} y={height + 11} textAnchor="middle" fontSize="10" fill="var(--muted)"
                fontWeight={i === shown ? 600 : 400}>{p.label}</text>
              {/* The hit target is the whole band, not just the painted bar. */}
              <rect x={PAD_X + band * i} y={0} width={band} height={height + 16} fill="transparent" tabIndex={v === null ? -1 : 0}
                aria-label={v === null ? undefined : `${p.label}: ${format(v)}`}
                onPointerEnter={() => setActive(i)} onPointerDown={() => setActive(i)} onFocus={() => setActive(i)}
                onPointerLeave={() => setActive(null)} onBlur={() => setActive(null)} style={{ outline: "none" }} />
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

/** A 2px line for a rate that changes over time, with an optional reference level. */
export function LineChart({ title, points, format, reference, height = 88 }: {
  title: string; points: Point[]; format: (v: number) => string;
  reference?: { value: number; label: string }; height?: number;
}) {
  const { shown, setActive, lastIndex } = useActive(points);
  const values = points.map((p) => p.value).filter((v): v is number => v !== null);
  if (values.length < 2) return null;
  const all = reference ? [...values, reference.value] : values;
  let min = Math.min(...all);
  let max = Math.max(...all);
  const padY = (max - min || 1) * 0.18;
  min -= padY;
  max += padY;
  const top = 8;
  const plot = height - top - 6;
  const band = (W - PAD_X * 2) / points.length;
  const x = (i: number) => PAD_X + band * i + band / 2;
  const y = (v: number) => top + ((max - v) / (max - min)) * plot;
  const path = points
    .map((p, i) => (p.value === null ? null : `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");

  return (
    <figure>
      <Readout title={title} label={points[shown]?.label ?? ""} value={shown >= 0 ? format(points[shown].value as number) : "–"} />
      <svg viewBox={`0 0 ${W} ${height + 16}`} className="mt-1 w-full" role="img"
        aria-label={`${title}: ${points.filter((p) => p.value !== null).map((p) => `${p.label} ${format(p.value as number)}`).join(", ")}`}>
        {reference && (
          <>
            <line x1={PAD_X} x2={W - PAD_X} y1={y(reference.value)} y2={y(reference.value)} stroke="var(--line)" strokeWidth="1" />
            <text x={W - PAD_X} y={y(reference.value) - 3} textAnchor="end" fontSize="10" fill="var(--faint)">{reference.label}</text>
          </>
        )}
        {shown >= 0 && shown !== lastIndex && (
          <line x1={x(shown)} x2={x(shown)} y1={top - 4} y2={height} stroke="var(--line)" strokeWidth="1" />
        )}
        <polyline points={path} fill="none" stroke="var(--chart)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {shown >= 0 && (
          <circle cx={x(shown)} cy={y(points[shown].value as number)} r="4" fill="var(--chart)" stroke="var(--surface)" strokeWidth="2" />
        )}
        {points.map((p, i) => (
          <g key={p.label}>
            <text x={x(i)} y={height + 11} textAnchor="middle" fontSize="10" fill="var(--muted)"
              fontWeight={i === shown ? 600 : 400}>{p.label}</text>
            <rect x={PAD_X + band * i} y={0} width={band} height={height + 16} fill="transparent" tabIndex={p.value === null ? -1 : 0}
              aria-label={p.value === null ? undefined : `${p.label}: ${format(p.value)}`}
              onPointerEnter={() => setActive(i)} onPointerDown={() => setActive(i)} onFocus={() => setActive(i)}
              onPointerLeave={() => setActive(null)} onBlur={() => setActive(null)} style={{ outline: "none" }} />
          </g>
        ))}
      </svg>
    </figure>
  );
}

/** Ranked horizontal bars for a split: one hue, largest first, the figure printed beside each bar. */
export function RankedBars({ rows }: { rows: { name: string; share: number; note?: string | null }[] }) {
  const max = Math.max(...rows.map((r) => r.share), 1);
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.name}>
          <div className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="min-w-0 truncate">{r.name}</span>
            <span className="num font-medium">{r.share.toFixed(1)}%</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-[var(--chart-soft)]" aria-hidden="true">
            <div className="h-1.5 rounded-full bg-[var(--chart)]" style={{ width: `${(100 * r.share) / max}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * Promised range against the delivered figure, on one scale. The band is the target
 * (a lighter step of the chart hue); the dot is what was delivered.
 */
export function TargetBar({ low, high, delivered, unit, tone }: {
  low: number | null; high: number | null; delivered: number; unit: string; tone: "up" | "down" | "ink";
}) {
  const lo = low ?? high;
  const hi = high ?? low;
  if (lo === null || hi === null) return null;
  const min = Math.min(lo, delivered);
  const max = Math.max(hi, delivered);
  const pad = Math.max((max - min) * 0.25, 1);
  const a = min - pad;
  const b = max + pad;
  const x = (v: number) => 8 + ((v - a) / (b - a)) * (W - 16);
  const point = lo === hi;
  const color = tone === "up" ? "var(--up)" : tone === "down" ? "var(--down)" : "var(--ink)";
  const fmt = (v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`;
  const targetLabel = point ? fmt(lo) : `${fmt(lo)} to ${fmt(hi)}`;
  const dx = x(delivered);
  const tx = (x(lo) + x(hi)) / 2;
  // Keep the two labels on opposite rows so they can never collide.
  return (
    <svg viewBox={`0 0 ${W} 46`} className="w-full" role="img"
      aria-label={`Target ${targetLabel}; delivered ${fmt(delivered)}`}>
      <text x={Math.min(Math.max(tx, 44), W - 44)} y="10" textAnchor="middle" fontSize="10" fill="var(--muted)">
        Target {targetLabel}
      </text>
      <line x1="8" x2={W - 8} y1="22" y2="22" stroke="var(--line)" strokeWidth="1" />
      {point
        ? <line x1={x(lo)} x2={x(lo)} y1="15" y2="29" stroke="var(--chart)" strokeWidth="2" strokeLinecap="round" />
        : <rect x={x(lo)} y="18" width={Math.max(x(hi) - x(lo), 2)} height="8" rx="4" fill="var(--chart-soft)" stroke="var(--chart)" strokeWidth="1" />}
      <circle cx={dx} cy="22" r="5" fill={color} stroke="var(--surface)" strokeWidth="2" />
      <text x={Math.min(Math.max(dx, 40), W - 40)} y="42" textAnchor="middle" fontSize="10" fontWeight="600" fill="var(--ink)">
        Delivered {fmt(delivered)}
      </text>
    </svg>
  );
}
