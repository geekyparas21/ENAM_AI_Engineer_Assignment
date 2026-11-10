"use client";

import { useSyncExternalStore } from "react";
import type { Category, Settings } from "./types";

/** Per-device state: no login, everything lives in localStorage. */
export type Theme = "system" | "light" | "dark";
export type WindowKey = "24h" | "3d" | "7d" | "30d" | "custom";

export interface Prefs {
  settings: Settings;
  theme: Theme;
  window: WindowKey;
  customFrom: string | null; // YYYY-MM-DD
  customTo: string | null;
  seen: Record<string, true>;      // announcement id
  starred: Record<string, true>;   // announcement id
  mutes: Record<string, true>;     // `${symbol}|${category}`
}

export const DEFAULT_SETTINGS: Settings = {
  volume_multiple: 2,
  price_move_pct: 5,
  alert_categories: [
    "results", "M&A", "management_change", "litigation", "fund_raise", "pledging", "credit_rating",
  ],
};

const DEFAULTS: Prefs = {
  settings: DEFAULT_SETTINGS,
  theme: "system",
  window: "24h",
  customFrom: null,
  customTo: null,
  seen: {},
  starred: {},
  mutes: {},
};

const KEY = "finn.prefs.v1";
let prefs: Prefs = DEFAULTS;
let loaded = false;
const listeners = new Set<() => void>();

function read(): Prefs {
  if (!loaded && typeof window !== "undefined") {
    loaded = true;
    try {
      const raw = window.localStorage.getItem(KEY);
      if (raw) {
        const saved = JSON.parse(raw) as Partial<Prefs>;
        prefs = { ...DEFAULTS, ...saved, settings: { ...DEFAULT_SETTINGS, ...saved.settings } };
      }
    } catch {
      // Private mode or corrupt value: fall back to defaults.
    }
  }
  return prefs;
}

export function update(patch: Partial<Prefs> | ((p: Prefs) => Partial<Prefs>)) {
  const current = read();
  prefs = { ...current, ...(typeof patch === "function" ? patch(current) : patch) };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Storage unavailable: the change still applies for this visit.
  }
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(subscribe, read, () => DEFAULTS);
}

export const muteKey = (symbol: string, category: Category) => `${symbol}|${category}`;

function toggleIn(map: Record<string, true>, key: string): Record<string, true> {
  const next = { ...map };
  if (next[key]) delete next[key];
  else next[key] = true;
  return next;
}

export const toggleSeen = (id: string) => update((p) => ({ seen: toggleIn(p.seen, id) }));
export const toggleStar = (id: string) => update((p) => ({ starred: toggleIn(p.starred, id) }));
export const toggleMute = (symbol: string, category: Category) =>
  update((p) => ({ mutes: toggleIn(p.mutes, muteKey(symbol, category)) }));
export const setSettings = (patch: Partial<Settings>) =>
  update((p) => ({ settings: { ...p.settings, ...patch } }));

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}
