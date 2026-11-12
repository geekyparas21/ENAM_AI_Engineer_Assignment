"use client";

import { useEffect, useState } from "react";
import type { Snapshot } from "./types";

/**
 * Cold-start-proof loading.
 * 1. The snapshot shipped with the frontend renders immediately (static file on the CDN).
 * 2. If a backend is configured, ask it for fresher data in the background and swap
 *    it in only if it is actually newer. A sleeping or failing backend changes nothing.
 */
const API = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "";

export type Source = "bundled" | "live";
interface State {
  data: Snapshot | null;
  source: Source;
  error: string | null;
  refreshing: boolean;
  /**
   * Why we are not showing live data. "none" = no backend is configured, so the committed
   * snapshot IS the current data and must not be labelled a stale fallback. Set to a reason
   * only when a live fetch was actually attempted and failed.
   */
  liveError: string | null;
}

let state: State = {
  data: null, source: "bundled", error: null, refreshing: false, liveError: null,
};
let started = false;
const listeners = new Set<() => void>();

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

async function fetchJson(url: string, timeoutMs: number): Promise<Snapshot> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status}`);
    return (await res.json()) as Snapshot;
  } finally {
    clearTimeout(timer);
  }
}

async function load() {
  try {
    set({ data: await fetchJson("/snapshot.json", 15000) });
  } catch {
    set({ error: "Could not load the saved snapshot." });
  }
  if (!API) return;
  set({ refreshing: true });
  try {
    const live = await fetchJson(`${API}/api/snapshot`, 45000);
    if (!state.data || live.generated_at > state.data.generated_at) {
      set({ data: live, source: "live", error: null, liveError: null });
    } else {
      set({ liveError: null });
    }
  } catch (err) {
    // Backend asleep or down: keep showing the snapshot, and record why, so the stamp can
    // say "live check failed" instead of silently implying the data is merely saved.
    const e = err as Error;
    set({ liveError: e.name === "AbortError" ? "backend did not respond" : `backend returned ${e.message}` });
  } finally {
    set({ refreshing: false });
  }
}

export function useSnapshot(): State {
  const [, force] = useState(0);
  useEffect(() => {
    const l = () => force((n) => n + 1);
    listeners.add(l);
    if (!started) {
      started = true;
      void load();
    }
    return () => {
      listeners.delete(l);
    };
  }, []);
  return state;
}

export const apiBase = API;
