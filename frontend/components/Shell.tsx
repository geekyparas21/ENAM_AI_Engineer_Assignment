"use client";

import type { ReactNode } from "react";
import { useSnapshot } from "@/lib/data";
import { dateTime } from "@/lib/format";
import type { Snapshot } from "@/lib/types";

export function PageTitle({ title, sub }: { title: string; sub?: ReactNode }) {
  return (
    <header className="pb-3 pt-2">
      <h1 className="display text-[30px] leading-9">{title}</h1>
      {sub && <p className="mt-1 text-[14px] leading-5 text-muted">{sub}</p>}
    </header>
  );
}

export function Skeletons({ count = 3 }: { count?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-3">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="card p-3.5">
          <div className="skeleton h-4 w-28" />
          <div className="skeleton mt-3 h-4 w-full" />
          <div className="skeleton mt-2 h-4 w-2/3" />
          <div className="skeleton mt-4 h-16 w-full" />
        </div>
      ))}
    </div>
  );
}

export function DataStamp({ snap, source, refreshing }: { snap: Snapshot; source: string; refreshing: boolean }) {
  const at = snap.as_of.announcements ?? snap.generated_at;
  return (
    <p className="num text-[11px] text-faint">
      Data as of {dateTime(at)} IST · {source === "live" ? "live" : "saved snapshot"}
      {refreshing ? " · checking for newer…" : ""}
    </p>
  );
}

/** Loading, error and ready states in one place, so every screen handles all three. */
export function WithSnapshot({ children }: {
  children: (snap: Snapshot, meta: { source: string; refreshing: boolean }) => ReactNode;
}) {
  const { data, error, source, refreshing } = useSnapshot();
  if (data) return <>{children(data, { source, refreshing })}</>;
  if (error) {
    return (
      <div className="card p-4 text-[14px]">
        <p className="font-medium">FINN could not load its data.</p>
        <p className="mt-1 text-muted">{error} Check your connection and reload.</p>
        <button type="button" onClick={() => window.location.reload()}
          className="mt-3 h-10 rounded-md bg-ink px-4 text-[13px] font-medium text-bg">Reload</button>
      </div>
    );
  }
  return <Skeletons />;
}
