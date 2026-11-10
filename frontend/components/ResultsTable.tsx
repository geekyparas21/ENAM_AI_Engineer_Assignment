import { amount, direction, pct } from "@/lib/format";
import type { Metric, ResultsDetail } from "@/lib/types";
import { WarnIcon } from "./icons";

function Row({ label, m, bold }: { label: string; m: Metric; bold?: boolean }) {
  return (
    <tr className="border-t border-line">
      <th scope="row" className={`py-1.5 pr-2 text-left text-[13px] ${bold ? "font-semibold" : "font-normal text-muted"}`}>
        {label}
      </th>
      <td className="num py-1.5 text-right text-[13px] font-medium">{amount(m.cur)}</td>
      <td className={`num py-1.5 pl-3 text-right text-[13px] ${direction(m.qoq_pct)}`}>{pct(m.qoq_pct)}</td>
      <td className={`num py-1.5 pl-3 text-right text-[13px] ${direction(m.yoy_pct)}`}>{pct(m.yoy_pct)}</td>
    </tr>
  );
}

function pp(value: number | null): string {
  if (value === null) return "–";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(1)}pp`;
}

function MarginRow({ label, m }: { label: string; m: Metric }) {
  return (
    <tr className="border-t border-line">
      <th scope="row" className="py-1.5 pr-2 text-left text-[13px] font-normal text-muted">{label}</th>
      <td className="num py-1.5 text-right text-[13px] font-medium">{m.cur === null ? "–" : `${m.cur.toFixed(1)}%`}</td>
      <td className={`num py-1.5 pl-3 text-right text-[13px] ${direction(m.qoq_pct)}`}>{pp(m.qoq_pct)}</td>
      <td className={`num py-1.5 pl-3 text-right text-[13px] ${direction(m.yoy_pct)}`}>{pp(m.yoy_pct)}</td>
    </tr>
  );
}

export function ResultsTable({ detail }: { detail: ResultsDetail }) {
  const failed = detail.checks.filter((c) => !c.ok);
  return (
    <div className="mt-3">
      <table className="w-full border-collapse">
        <thead>
          <tr className="label">
            <th scope="col" className="pb-1 text-left font-medium">{detail.basis} · {detail.unit}</th>
            <th scope="col" className="pb-1 text-right font-medium">{detail.period ?? "Qtr"}</th>
            <th scope="col" className="pb-1 pl-3 text-right font-medium">QoQ</th>
            <th scope="col" className="pb-1 pl-3 text-right font-medium">YoY</th>
          </tr>
        </thead>
        <tbody>
          <Row label="Revenue" m={detail.metrics.revenue} bold />
          <Row label="EBITDA" m={detail.metrics.ebitda} bold />
          <MarginRow label="EBITDA margin" m={detail.margins.ebitda} />
          <Row label="PBT" m={detail.metrics.pbt} bold />
          <Row label="PAT" m={detail.metrics.pat} bold />
          <MarginRow label="PAT margin" m={detail.margins.pat} />
        </tbody>
      </table>
      <p className="mt-2 text-[11px] leading-4 text-faint">
        {detail.source_note} {detail.ebitda_definition}
      </p>
      {failed.length > 0 && (
        <p className="mt-2 flex gap-1.5 rounded-md bg-sunken px-2 py-1.5 text-[12px] leading-4 text-warn">
          <WarnIcon width={14} height={14} className="mt-px shrink-0" />
          <span>Check before relying on these: {failed.map((c) => c.note).join(" ")}</span>
        </p>
      )}
    </div>
  );
}
