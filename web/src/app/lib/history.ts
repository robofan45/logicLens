// Local analysis history. Lives only in this browser (localStorage); nothing is uploaded.
// Every read is validated: storage can be empty, blocked, full, or edited by hand.

import { isPlatformId, type PlatformId } from "./platforms";

export interface HistoryEntry {
  id: string;
  name: string;
  createdAt: string; // ISO
  platform: PlatformId;
  source: "text" | "image";
  text: string;
  rungs: number;
  riskScore: number;
  grade: string;
  counts: { critical: number; high: number; medium: number; low: number };
  topFindings: string[];
}

const KEY = "logiclens.history.v1";
export const HISTORY_LIMITS = { entries: 50, bytes: 2_500_000, textChars: 200_000 };

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const num = (x: unknown) => (typeof x === "number" && Number.isFinite(x) ? x : 0);

function sanitize(x: unknown): HistoryEntry | null {
  if (!isObj(x)) return null;
  if (typeof x.id !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(x.id)) return null;
  if (typeof x.text !== "string" || x.text.length > HISTORY_LIMITS.textChars) return null;
  const created = typeof x.createdAt === "string" && !Number.isNaN(Date.parse(x.createdAt)) ? x.createdAt : null;
  if (!created) return null;
  const counts = isObj(x.counts) ? x.counts : {};
  return {
    id: x.id,
    name: typeof x.name === "string" ? x.name.slice(0, 120) : "Untitled analysis",
    createdAt: created,
    platform: isPlatformId(x.platform) ? x.platform : "unknown",
    source: x.source === "image" ? "image" : "text",
    text: x.text,
    rungs: num(x.rungs),
    riskScore: Math.max(0, Math.min(100, num(x.riskScore))),
    grade: typeof x.grade === "string" ? x.grade.slice(0, 32) : "",
    counts: { critical: num(counts.critical), high: num(counts.high), medium: num(counts.medium), low: num(counts.low) },
    topFindings: Array.isArray(x.topFindings) ? x.topFindings.filter((t): t is string => typeof t === "string").map((t) => t.slice(0, 200)).slice(0, 5) : [],
  };
}

export function loadHistory(): HistoryEntry[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return [];
  }
  if (!raw || raw.length > HISTORY_LIMITS.bytes * 2) return [];
  try {
    const data = JSON.parse(raw) as unknown;
    if (!Array.isArray(data)) return [];
    return data.map(sanitize).filter((e): e is HistoryEntry => e !== null).slice(0, HISTORY_LIMITS.entries);
  } catch {
    return [];
  }
}

function persist(entries: HistoryEntry[]): boolean {
  let list = entries.slice(0, HISTORY_LIMITS.entries);
  // keep the newest entries that fit in the byte budget
  while (list.length && JSON.stringify(list).length > HISTORY_LIMITS.bytes) list = list.slice(0, -1);
  try {
    localStorage.setItem(KEY, JSON.stringify(list));
    return true;
  } catch {
    return false;
  }
}

export function newId(): string {
  const rnd = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return rnd.replace(/[^A-Za-z0-9-]/g, "").slice(0, 36);
}

export function saveToHistory(entry: HistoryEntry): boolean {
  const clean = sanitize(entry);
  if (!clean) return false;
  const rest = loadHistory().filter((e) => e.id !== clean.id && e.text !== clean.text);
  return persist([clean, ...rest]);
}

export function getHistoryEntry(id: string): HistoryEntry | undefined {
  return loadHistory().find((e) => e.id === id);
}

export function deleteHistoryEntry(id: string): void {
  persist(loadHistory().filter((e) => e.id !== id));
}

export function clearHistory(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
}
