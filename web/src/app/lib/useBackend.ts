// Backend status for the whole app: one /health + /api/meta probe, shared by every component.

import { useEffect, useSyncExternalStore } from "react";
import { api, type Health, type Meta } from "./api";
import { STANDALONE } from "./runtime";

export interface BackendState {
  status: "checking" | "online" | "offline";
  health: Health | null;
  meta: Meta | null;
  checkedAt: number;
}

let state: BackendState = { status: "checking", health: null, meta: null, checkedAt: 0 };
const listeners = new Set<() => void>();
let inflight: Promise<void> | null = null;
// While the API is unreachable, look again every 15 s (it may still be starting, e.g. the first
// run of Start-LogicLens.cmd installs its packages). Gives up after ~10 minutes.
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let retries = 0;
const RETRY_MS = 15_000;
const MAX_RETRIES = 40;

function set(next: BackendState) {
  state = next;
  listeners.forEach((l) => l());
}

export function refreshBackend(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      if (STANDALONE) throw new Error("standalone copy: no LogicLens server");
      const health = await api.health();
      if (!health || typeof health !== "object" || typeof health.status !== "string" || typeof health.version !== "string") {
        throw new Error("not a LogicLens server");
      }
      let meta: Meta | null = null;
      try {
        meta = await api.meta();
      } catch {
        meta = null; // e.g. API key required: health is open, meta is not
      }
      retries = 0;
      set({ status: "online", health, meta, checkedAt: Date.now() });
    } catch {
      set({ status: "offline", health: null, meta: null, checkedAt: Date.now() });
      if (!STANDALONE && !retryTimer && retries < MAX_RETRIES) {
        retries++;
        retryTimer = setTimeout(() => {
          retryTimer = null;
          void refreshBackend();
        }, RETRY_MS);
      }
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Test hook: reset the shared state between tests. */
export function __resetBackendState(): void {
  state = { status: "checking", health: null, meta: null, checkedAt: 0 };
  inflight = null;
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = null;
  retries = 0;
}

export function useBackend(): BackendState & { refresh: () => Promise<void> } {
  const snap = useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => state,
    () => state,
  );
  useEffect(() => {
    if (state.checkedAt === 0 && !inflight) void refreshBackend();
  }, []);
  return { ...snap, refresh: refreshBackend };
}

export function llmEnabled(s: BackendState): boolean {
  return s.status === "online" && !!s.meta?.llm?.enabled;
}

export function visionEnabled(s: BackendState): boolean {
  if (s.status !== "online") return false;
  if (!s.meta) return true; // unknown (e.g. key needed): let the request tell us
  return !!s.meta.engines?.active;
}
