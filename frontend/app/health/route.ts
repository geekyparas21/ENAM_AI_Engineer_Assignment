import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Snapshot } from "@/lib/types";

/**
 * Ingest health for the live site: when data last landed, how much of it there is, and
 * what the last ingestion error was.
 *
 * The snapshot read is cached because that file only ever changes by being committed, and
 * the commit triggers a rebuild. The staleness age is computed per request instead, so
 * "how old is this data" is answered at the time of asking rather than at build time.
 */
const STALE_AFTER_HOURS = 24;

interface Facts {
  last_successful_ingest: string | null;
  last_ingest_attempt: string | null;
  last_error: string | null;
  item_count: number;
  material_count: number;
  latest_filing_ts: string | null;
  last_trading_session: string | null;
  prices_as_of: string | null;
  snapshot_generated_at: string;
  companies_tracked: number;
}

async function snapshotFacts(): Promise<Facts | { unreadable: string }> {
  "use cache";
  let snap: Snapshot;
  try {
    const file = path.join(process.cwd(), "public", "snapshot.json");
    snap = JSON.parse(await readFile(file, "utf-8")) as Snapshot;
  } catch (err) {
    return { unreadable: (err as Error).message };
  }

  const items = snap.announcements ?? [];
  return {
    last_successful_ingest:
      snap.ingest?.last_ok_at ?? snap.as_of.announcements ?? snap.generated_at,
    last_ingest_attempt: snap.ingest?.last_attempted_at ?? null,
    last_error: snap.ingest?.last_error ?? null,
    item_count: items.length,
    material_count: items.filter((a) => a.score >= snap.material_threshold).length,
    latest_filing_ts: items.reduce<string | null>(
      (max, a) => (max === null || a.ts > max ? a.ts : max),
      null,
    ),
    last_trading_session: snap.as_of.last_session ?? null,
    prices_as_of: snap.as_of.prices ?? null,
    snapshot_generated_at: snap.generated_at,
    companies_tracked: snap.portfolio?.length ?? 0,
  };
}

export async function GET() {
  const facts = await snapshotFacts();
  if ("unreadable" in facts) {
    return Response.json(
      { status: "error", last_error: `snapshot unreadable: ${facts.unreadable}` },
      { status: 500 },
    );
  }

  const last = facts.last_successful_ingest;
  const ageHours = last ? (Date.now() - new Date(last).getTime()) / 3_600_000 : null;
  const stale = ageHours !== null && ageHours > STALE_AFTER_HOURS;

  return Response.json(
    {
      status: facts.last_error ? "degraded" : stale ? "stale" : "ok",
      ...facts,
      ingest_age_hours: ageHours === null ? null : Math.round(ageHours * 10) / 10,
      stale_after_hours: STALE_AFTER_HOURS,
    },
    { headers: { "cache-control": "no-store" } },
  );
}
