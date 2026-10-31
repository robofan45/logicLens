// LogicLens backend client (contract/README.md §2, §4, §5; backend/README.md).
//
// The backend only does what needs a server: image recognition and Claude explanations/chat.
// Everything deterministic (trace, faults, Structured Text, simulator) runs in the browser.
// Base URL: VITE_API_BASE at build time; empty = same origin (the Vite dev server and the
// nginx image both proxy /api and /health to the backend).

import { isPlatformId, type PlatformId } from "./platforms";

const RAW_BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? "";
export const API_BASE = RAW_BASE.replace(/\/+$/, "");

const KEY_STORAGE = "logiclens.apiKey";

/** API key for servers that set LOGICLENS_API_KEYS. Kept in sessionStorage (tab lifetime only). */
export const apiKey = {
  get(): string {
    try {
      return sessionStorage.getItem(KEY_STORAGE) ?? "";
    } catch {
      return "";
    }
  },
  set(value: string): void {
    try {
      if (value) sessionStorage.setItem(KEY_STORAGE, value.trim());
      else sessionStorage.removeItem(KEY_STORAGE);
    } catch {
      /* storage blocked: the key just isn't remembered */
    }
  },
};

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
    public retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ------------------------------------------------------------------ response types

export type BBox = [number, number, number, number];

export interface ElementOut {
  index: number;
  mnemonic: string;
  operands?: string[];
  bbox?: BBox | null;
  confidence?: number | null;
}

export interface RungOut {
  number: number;
  comment?: string | null;
  text: string;
  confidence?: number | null;
  bbox?: BBox | null;
  elements?: ElementOut[];
}

export interface DetectionOut {
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: BBox;
}

export interface ProgramResponse {
  schema_version: "1.0";
  source: "image" | "text";
  platform: PlatformId;
  platform_confidence?: number | null;
  rungs: RungOut[];
  detections?: DetectionOut[] | null;
  image?: { width: number; height: number; quality?: { overall: number; blur: number; contrast: number } | null } | null;
  warnings: string[];
  engine: { name: string; version?: string | null; model?: string | null };
  timing_ms?: Record<string, number> | null;
}

export interface Health {
  status: string;
  version: string;
  auth: "open" | "api_key" | string;
  warnings?: string[];
}

export interface Meta {
  name: string;
  version: string;
  auth: string;
  engines: { configured: string; active: string | null; available: Record<string, boolean> };
  ocr: boolean;
  llm: { enabled: boolean; models: Record<string, string> };
  limits: {
    upload_mb: number;
    max_image_side: number;
    program_chars: number;
    llm_program_chars: number;
    rungs: number;
    [k: string]: unknown;
  };
  platforms: string[];
}

export interface ExplainFinding {
  id?: string;
  rule?: string;
  severity?: string;
  title?: string;
  description?: string;
  recommendation?: string;
  rungs?: number[];
}

export interface ExplainResponse {
  summary: string;
  rung_explanations: { rung: number; text: string }[];
  ai_findings: { severity: "critical" | "high" | "medium" | "low"; title: string; rungs: number[]; description: string; recommendation: string }[];
  model: string;
  disclaimer: string;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  answer: string;
  model: string;
  disclaimer: string;
}

// ------------------------------------------------------------------ validation of server data

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const isStr = (x: unknown, max = 100_000): x is string => typeof x === "string" && x.length <= max;
const isBox = (x: unknown): x is BBox => Array.isArray(x) && x.length === 4 && x.every(isNum);

function bad(what: string): never {
  throw new ApiError("E_BAD_RESPONSE", `The server sent an unexpected response (${what}).`, 0);
}

/** Checks the parts of a program response the UI relies on; drops anything malformed it can. */
export function validateProgram(data: unknown): ProgramResponse {
  if (!isObj(data)) bad("not an object");
  if (!Array.isArray(data.rungs) || data.rungs.length > 2000) bad("rungs");
  const rungs: RungOut[] = data.rungs.map((r, i) => {
    if (!isObj(r) || !isStr(r.text, 4000) || !isNum(r.number)) bad(`rung ${i}`);
    const elements = Array.isArray(r.elements)
      ? r.elements
          .filter((e): e is Record<string, unknown> => isObj(e) && isNum(e.index) && isStr(e.mnemonic, 8))
          .slice(0, 256)
          .map((e) => ({
            index: e.index as number,
            mnemonic: e.mnemonic as string,
            operands: Array.isArray(e.operands) ? e.operands.filter((o): o is string => isStr(o, 120)).slice(0, 8) : [],
            bbox: isBox(e.bbox) ? e.bbox : null,
            confidence: isNum(e.confidence) ? e.confidence : null,
          }))
      : [];
    return {
      number: r.number,
      comment: isStr(r.comment, 2000) ? r.comment : null,
      text: r.text,
      confidence: isNum(r.confidence) ? r.confidence : null,
      bbox: isBox(r.bbox) ? r.bbox : null,
      elements,
    };
  });
  const detections = Array.isArray(data.detections)
    ? data.detections
        .filter((d): d is Record<string, unknown> => isObj(d) && isBox(d.bbox) && isNum(d.confidence) && isStr(d.class_name, 64))
        .slice(0, 5000)
        .map((d) => ({ class_id: isNum(d.class_id) ? d.class_id : -1, class_name: d.class_name as string, confidence: d.confidence as number, bbox: d.bbox as BBox }))
    : [];
  const engine = isObj(data.engine) && isStr(data.engine.name, 64)
    ? { name: data.engine.name, version: isStr(data.engine.version, 64) ? data.engine.version : null, model: isStr(data.engine.model, 256) ? data.engine.model : null }
    : bad("engine");
  const image = isObj(data.image) && isNum(data.image.width) && isNum(data.image.height)
    ? {
        width: data.image.width,
        height: data.image.height,
        quality: isObj(data.image.quality) && isNum(data.image.quality.overall)
          ? { overall: data.image.quality.overall, blur: Number(data.image.quality.blur) || 0, contrast: Number(data.image.quality.contrast) || 0 }
          : null,
      }
    : null;
  return {
    schema_version: "1.0",
    source: data.source === "text" ? "text" : "image",
    platform: isPlatformId(data.platform) ? data.platform : "unknown",
    platform_confidence: isNum(data.platform_confidence) ? data.platform_confidence : null,
    rungs,
    detections,
    image,
    warnings: Array.isArray(data.warnings) ? data.warnings.filter((w): w is string => isStr(w, 500)).slice(0, 200) : [],
    engine,
    timing_ms: isObj(data.timing_ms)
      ? Object.fromEntries(Object.entries(data.timing_ms).filter(([, v]) => isNum(v))) as Record<string, number>
      : null,
  };
}

function validateExplain(data: unknown): ExplainResponse {
  if (!isObj(data) || !isStr(data.summary) || !isStr(data.disclaimer)) bad("explain");
  const sev = new Set(["critical", "high", "medium", "low"]);
  return {
    summary: data.summary,
    model: isStr(data.model, 128) ? data.model : "",
    disclaimer: data.disclaimer,
    rung_explanations: Array.isArray(data.rung_explanations)
      ? data.rung_explanations.filter((r): r is { rung: number; text: string } => isObj(r) && isNum(r.rung) && isStr(r.text, 4000))
      : [],
    ai_findings: Array.isArray(data.ai_findings)
      ? data.ai_findings
          .filter((f): f is Record<string, unknown> => isObj(f) && isStr(f.title, 200) && isStr(f.description, 4000))
          .map((f) => ({
            severity: (sev.has(f.severity as string) ? f.severity : "low") as ExplainResponse["ai_findings"][number]["severity"],
            title: f.title as string,
            description: f.description as string,
            recommendation: isStr(f.recommendation, 4000) ? (f.recommendation as string) : "",
            rungs: Array.isArray(f.rungs) ? (f.rungs as unknown[]).filter(isNum) : [],
          }))
      : [],
  };
}

function validateChat(data: unknown): ChatResponse {
  if (!isObj(data) || !isStr(data.answer) || !isStr(data.disclaimer)) bad("chat");
  return { answer: data.answer, model: isStr(data.model, 128) ? data.model : "", disclaimer: data.disclaimer };
}

// ------------------------------------------------------------------ transport

const FRIENDLY: Record<string, string> = {
  E_NETWORK: "Can't reach the LogicLens server. Image recognition and AI explanations need it; pasted ladder text is still analysed in your browser.",
  E_CLIENT_TIMEOUT: "The server took too long to answer.",
  E_ENGINE_UNAVAILABLE: "The server has no image-recognition engine configured (needs LOGICLENS_YOLO_ONNX or ANTHROPIC_API_KEY).",
  E_LLM_DISABLED: "AI explanations are switched off on this server (needs ANTHROPIC_API_KEY).",
  E_UNAUTHORIZED: "The server needs an API key. Add it under Analysis settings.",
  E_RATE_LIMITED: "Too many requests. Wait a moment and try again.",
  E_BUSY: "The server is busy. Try again in a few seconds.",
  E_TOO_LARGE: "The file is too large for the server.",
  E_UNSUPPORTED_MEDIA: "Use a PNG, JPEG or WEBP image.",
  E_BAD_IMAGE: "The image could not be decoded (corrupt, too large or truncated).",
};

export function friendlyMessage(err: unknown): string {
  if (err instanceof ApiError) return FRIENDLY[err.code] ?? err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  json?: unknown;
  timeoutMs?: number;
  signal?: AbortSignal;
}

async function request(path: string, opts: RequestOptions = {}): Promise<unknown> {
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctrl.abort();
  }, opts.timeoutMs ?? 30_000);
  const onAbort = () => ctrl.abort();
  opts.signal?.addEventListener("abort", onAbort, { once: true });
  const headers: Record<string, string> = { Accept: "application/json" };
  const key = apiKey.get();
  if (key) headers["X-API-Key"] = key;
  let body = opts.body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? (body ? "POST" : "GET"),
      body,
      headers,
      signal: ctrl.signal,
      credentials: "omit",
      cache: "no-store",
    });
  } catch (e) {
    if (timedOut) throw new ApiError("E_CLIENT_TIMEOUT", FRIENDLY.E_CLIENT_TIMEOUT, 0);
    if (opts.signal?.aborted) throw new ApiError("E_ABORTED", "Cancelled.", 0);
    throw new ApiError("E_NETWORK", FRIENDLY.E_NETWORK, 0, String(e));
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener("abort", onAbort);
  }
  let data: unknown = null;
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const env = isObj(data) && isObj(data.error) ? data.error : {};
    const retry = Number(res.headers.get("Retry-After"));
    throw new ApiError(
      isStr(env.code, 64) ? env.code : `HTTP_${res.status}`,
      isStr(env.message, 500) ? env.message : `The server answered ${res.status}.`,
      res.status,
      env.details,
      Number.isFinite(retry) && retry > 0 ? retry : undefined,
    );
  }
  return data;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(id); reject(new ApiError("E_ABORTED", "Cancelled.", 0)); }, { once: true });
  });

/**
 * Retry when the server sheds load (503 E_BUSY / 429) and says when to come back. Image
 * recognition is CPU-bound, so short bursts are normal; waiting Retry-After beats failing.
 */
export async function withBackoff<T>(fn: () => Promise<T>, signal?: AbortSignal, maxRetries = 2, maxWaitS = 10): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (e) {
      if (signal?.aborted) throw new ApiError("E_ABORTED", "Cancelled.", 0);
      const retryable = e instanceof ApiError && (e.code === "E_BUSY" || e.code === "E_RATE_LIMITED") && (e.retryAfter ?? 0) <= maxWaitS;
      if (!retryable || attempt >= maxRetries) throw e;
      await sleep(Math.max(1, (e as ApiError).retryAfter ?? 2) * 1000, signal);
    }
  }
}

export const api = {
  health: (signal?: AbortSignal) => request("/health", { timeoutMs: 5_000, signal }) as Promise<Health>,

  meta: (signal?: AbortSignal) => request("/api/meta", { timeoutMs: 8_000, signal }) as Promise<Meta>,

  parseImage: async (file: Blob, platform?: PlatformId, signal?: AbortSignal): Promise<ProgramResponse> => {
    const form = new FormData();
    form.append("file", file, (file as File).name || "diagram.png");
    if (platform && platform !== "unknown") form.append("platform", platform);
    return validateProgram(await withBackoff(() => request("/api/analyze/parse", { body: form, timeoutMs: 120_000, signal }), signal));
  },

  parseText: async (text: string, platform?: PlatformId, signal?: AbortSignal): Promise<ProgramResponse> =>
    validateProgram(
      await request("/api/analyze/text", {
        json: { text, ...(platform && platform !== "unknown" ? { platform } : {}) },
        timeoutMs: 30_000,
        signal,
      }),
    ),

  explain: async (
    body: { program_text: string; platform?: PlatformId; user_context?: string; findings?: ExplainFinding[]; depth?: "standard" | "deep" },
    signal?: AbortSignal,
  ): Promise<ExplainResponse> => {
    const json = { ...body, platform: body.platform && body.platform !== "unknown" ? body.platform : undefined };
    return validateExplain(await withBackoff(() => request("/api/analyze/explain", { json, timeoutMs: 150_000, signal }), signal, 1));
  },

  chat: async (body: { program_text: string; question: string; history?: ChatTurn[] }, signal?: AbortSignal): Promise<ChatResponse> =>
    validateChat(await request("/api/chat", { json: body, timeoutMs: 120_000, signal })),
};
