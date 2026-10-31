// @vitest-environment jsdom
// Unit tests for the web app's library code: API client, history store, report, file names.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiKey, ApiError, friendlyMessage, validateProgram, withBackoff } from "../../../src/app/lib/api";
import { clearHistory, getHistoryEntry, HISTORY_LIMITS, loadHistory, saveToHistory, type HistoryEntry } from "../../../src/app/lib/history";
import { buildReport, mdEscape, mdFence } from "../../../src/app/lib/report";
import { safeFileName } from "../../../src/app/lib/download";
import { defaultWiring } from "../../../src/app/components/SimulatorPanel";
import { programTextFromResponse } from "../../../src/app/components/ImagePanel";
import { analyzeProgram, parseProgram } from "../../../src/engine";
import { mockFetch } from "../../helpers/ui";
import { __resetBackendState, refreshBackend, useBackend } from "../../../src/app/lib/useBackend";
import { renderHook, waitFor as waitForHook } from "@testing-library/react";

const entry = (over: Partial<HistoryEntry> = {}): HistoryEntry => ({
  id: "abc-123",
  name: "Motor",
  createdAt: "2026-10-31T10:00:00.000Z",
  platform: "rockwell_logix",
  source: "text",
  text: "XIC(A)OTE(B);",
  rungs: 1,
  riskScore: 10,
  grade: "Healthy",
  counts: { critical: 0, high: 0, medium: 1, low: 0 },
  topFindings: ["x"],
  ...over,
});

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("maps the contract error envelope to ApiError with code, status and Retry-After", async () => {
    mockFetch({ "/api/analyze/text": { status: 429, body: { error: { code: "E_RATE_LIMITED", message: "slow down", request_id: "r1" } }, headers: { "Retry-After": "7" } } });
    const err = await api.parseText("XIC(A)OTE(B);").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ code: "E_RATE_LIMITED", status: 429, retryAfter: 7 });
    expect(friendlyMessage(err)).toMatch(/Too many requests/);
  });

  it("reports a dead network as E_NETWORK with a helpful message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const err = await api.health().catch((e) => e);
    expect(err.code).toBe("E_NETWORK");
    expect(friendlyMessage(err)).toMatch(/still analysed in your browser/);
  });

  it("times out instead of hanging", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn((_: unknown, init?: RequestInit) => new Promise((_r, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })));
    const p = api.health().catch((e) => e);
    await vi.advanceTimersByTimeAsync(5_001);
    expect((await p).code).toBe("E_CLIENT_TIMEOUT");
    vi.useRealTimers();
  });

  it("sends the API key from sessionStorage and never sends cookies", async () => {
    apiKey.set("k".repeat(20));
    const { calls } = mockFetch({ "/health": { body: { status: "ok", version: "2", auth: "api_key" } } });
    await api.health();
    const init = calls[0].init!;
    expect((init.headers as Record<string, string>)["X-API-Key"]).toBe("k".repeat(20));
    expect(init.credentials).toBe("omit");
    apiKey.set("");
    expect(sessionStorage.getItem("logiclens.apiKey")).toBeNull();
  });

  it("handles a non-JSON error body", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502 })));
    const err = await api.meta().catch((e) => e);
    expect(err).toMatchObject({ code: "HTTP_502", status: 502 });
  });

  it("validateProgram rejects broken payloads and drops malformed parts", () => {
    expect(() => validateProgram(null)).toThrow(ApiError);
    expect(() => validateProgram({ rungs: "nope" })).toThrow(/unexpected response/);
    expect(() => validateProgram({ rungs: [{ number: 0, text: 5 }], engine: { name: "x" } })).toThrow();
    const ok = validateProgram({
      rungs: [{ number: 0, text: "XIC(A)OTE(B);", elements: [{ index: 0, mnemonic: "XIC", bbox: [1, 2, 3, 4] }, { index: "bad" }, null] }],
      detections: [{ class_name: "NO_Contact", confidence: 0.9, bbox: [0, 0, 1, 1] }, { bbox: "x" }],
      engine: { name: "yolo-onnx" },
      platform: "not-a-platform",
      warnings: ["w", 3],
    });
    expect(ok.rungs[0].elements).toHaveLength(1);
    expect(ok.detections).toHaveLength(1);
    expect(ok.platform).toBe("unknown");
    expect(ok.warnings).toEqual(["w"]);
  });

  it("programTextFromResponse keeps rung numbers and comments so they survive re-parsing", () => {
    const text = programTextFromResponse(validateProgram({
      rungs: [{ number: 3, comment: "start", text: "XIC(A)OTE(B);" }, { number: 7, text: "XIC(C)OTE(D);" }],
      engine: { name: "stub" },
    }));
    const parsed = parseProgram(text);
    expect(parsed.rungs.map((r) => r.number)).toEqual([3, 7]);
    expect(parsed.rungs[0].comment).toBe("start");
  });
});

describe("backoff on load shedding", () => {
  it("retries E_BUSY after Retry-After and then succeeds", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const p = withBackoff(async () => {
      calls++;
      if (calls < 3) throw new ApiError("E_BUSY", "busy", 503, undefined, 2);
      return "ok";
    });
    await vi.advanceTimersByTimeAsync(4_100);
    await expect(p).resolves.toBe("ok");
    expect(calls).toBe(3);
    vi.useRealTimers();
  });

  it("gives up after the retry budget and never retries other errors", async () => {
    let n = 0;
    await expect(withBackoff(async () => { n++; throw new ApiError("E_BAD_IMAGE", "bad", 422); })).rejects.toMatchObject({ code: "E_BAD_IMAGE" });
    expect(n).toBe(1);
    let m = 0;
    await expect(withBackoff(async () => { m++; throw new ApiError("E_BUSY", "busy", 503, undefined, 60); })).rejects.toMatchObject({ code: "E_BUSY" });
    expect(m).toBe(1); // Retry-After longer than the cap: surface it to the user instead of hanging
  });

  it("stops waiting when the user cancels", async () => {
    const ctrl = new AbortController();
    const p = withBackoff(async () => { throw new ApiError("E_BUSY", "busy", 503, undefined, 5); }, ctrl.signal);
    ctrl.abort();
    await expect(p).rejects.toMatchObject({ code: "E_ABORTED" });
  });
});

describe("history store", () => {
  it("round-trips an entry and puts the newest first", () => {
    saveToHistory(entry({ id: "a1", text: "XIC(A)OTE(B);" }));
    saveToHistory(entry({ id: "b2", text: "XIC(C)OTE(D);" }));
    expect(loadHistory().map((e) => e.id)).toEqual(["b2", "a1"]);
    expect(getHistoryEntry("a1")?.name).toBe("Motor");
  });

  it("replaces an older entry for the same program instead of duplicating it", () => {
    saveToHistory(entry({ id: "a1" }));
    saveToHistory(entry({ id: "a2" }));
    expect(loadHistory().map((e) => e.id)).toEqual(["a2"]);
  });

  it("survives corrupted, hostile or oversized storage", () => {
    localStorage.setItem("logiclens.history.v1", "{not json");
    expect(loadHistory()).toEqual([]);
    localStorage.setItem("logiclens.history.v1", JSON.stringify([{ id: "../../etc", text: "x", createdAt: "2026-01-01" }, { id: "ok", text: 5 }, 42, null]));
    expect(loadHistory()).toEqual([]);
    localStorage.setItem("logiclens.history.v1", JSON.stringify([{ ...entry(), riskScore: 1e9, platform: "evil", topFindings: [1, "a"], name: "n".repeat(500) }]));
    const [e] = loadHistory();
    expect(e.riskScore).toBe(100);
    expect(e.platform).toBe("unknown");
    expect(e.topFindings).toEqual(["a"]);
    expect(e.name).toHaveLength(120);
  });

  it("caps the number of entries", () => {
    for (let i = 0; i < HISTORY_LIMITS.entries + 5; i++) saveToHistory(entry({ id: `e${i}`, text: `XIC(A${i})OTE(B);` }));
    expect(loadHistory()).toHaveLength(HISTORY_LIMITS.entries);
  });

  it("returns false instead of throwing when storage is full", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("full", "QuotaExceededError"); });
    expect(saveToHistory(entry())).toBe(false);
    spy.mockRestore();
    clearHistory();
    expect(loadHistory()).toEqual([]);
  });
});

describe("report", () => {
  it("escapes Markdown so a crafted tag cannot inject links, images or HTML", () => {
    const evil = '![x](https://evil.example/p.png) <script>alert(1)</script> [click](javascript:alert(1))';
    const out = mdEscape(evil);
    expect(out).not.toMatch(/!\[x\]\(/);
    expect(out).not.toContain("<script>");
    expect(out).not.toMatch(/\[click\]\(/);
  });

  it("fences code with a fence longer than any backtick run inside", () => {
    const f = mdFence("a ``` b ```` c");
    expect(f.startsWith("`````")).toBe(true);
  });

  it("contains findings, checklist, corrections, Structured Text and the program", () => {
    const text = 'XIC(A)OTE("![a](http://x)");\nXIC(B)OTE("![a](http://x)");\n[XIC(S),XIC(M)]XIO(Stop)OTE(M);\nXIC(R)OTE(M);';
    const analysis = analyzeProgram(text);
    const md = buildReport({ name: "Demo <b>", platform: "rockwell_logix", generatedAt: "2026-10-31", programText: text, analysis, source: "text" });
    expect(md).toContain("# LogicLens analysis: Demo \\<b\\>");
    expect(md).toContain("DUPLICATE_OUTPUT");
    expect(md).toContain("## Checklist");
    expect(md).toContain("PROGRAM");
    // outside fenced code blocks nothing user-derived may form Markdown syntax
    const prose = md.replace(/(`{3,})[\s\S]*?\1/g, "");
    expect(prose).not.toMatch(/[^\\]!\[a\]\(http/);
    expect(prose).toContain("\\!\\[a\\]\\(http");
  });
});

describe("small helpers", () => {
  it("safeFileName strips paths and odd characters", () => {
    expect(safeFileName("../../etc/passwd", "md")).toBe("etc_passwd.md");
    expect(safeFileName("Pump P-101 (rev 2)", "st")).toBe("Pump_P-101_rev_2.st");
    expect(safeFileName("", "json")).toBe("logiclens.json");
  });

  it("defaultWiring makes stop / E-stop / overload devices NC and the rest NO", () => {
    for (const t of ["Stop_PB", "E_STOP", "EStop", "Emergency_Stop", "OL_Relay", "Motor1_Overload", "GUARD_SW"]) expect(defaultWiring(t)).toBe("NC");
    for (const t of ["Start_PB", "PE_Blocked", "Level_Low", "I:1/3", "Stopwatch_Reset"]) expect(defaultWiring(t)).toBe("NO");
  });
});


describe("backend detection", () => {
  beforeEach(() => __resetBackendState());
  afterEach(() => { __resetBackendState(); vi.useRealTimers(); });

  it("a host that answers /health with HTML (e.g. the page's own host) is not a LogicLens server", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<!doctype html><html></html>", { status: 200, headers: { "Content-Type": "text/html" } })));
    const { result } = renderHook(() => useBackend());
    await waitForHook(() => expect(result.current.status).toBe("offline"));
  });

  it("keeps looking every 15 s while the API is starting, then goes online", async () => {
    vi.useFakeTimers();
    let up = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (!up) throw new TypeError("Failed to fetch");
      const path = String(input);
      const body = path.endsWith("/health") ? { status: "ok", version: "2.0.0", auth: "open" } : { engines: { active: "yolo-onnx", available: {} }, llm: { enabled: false, models: {} }, limits: {} };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    await refreshBackend();
    const { result } = renderHook(() => useBackend());
    expect(result.current.status).toBe("offline");
    up = true;
    await vi.advanceTimersByTimeAsync(15_100);
    expect(result.current.status).toBe("online");
  });
});
