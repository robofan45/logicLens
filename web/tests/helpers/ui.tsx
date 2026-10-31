// Shared helpers for DOM tests (jsdom).
import { render } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router";
import { vi } from "vitest";
import { routes } from "../../src/app/routes";
import { __resetBackendState } from "../../src/app/lib/useBackend";

export function renderAt(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] });
  return { router, ...render(<RouterProvider router={router} />) };
}

export interface FakeRoute {
  status?: number;
  body: unknown;
  headers?: Record<string, string>;
}

/** Replace fetch with a router of canned JSON responses; unknown paths fail like a dead network. */
export function mockFetch(routes: Record<string, FakeRoute | ((init?: RequestInit) => FakeRoute)>) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const hit = routes[path];
    if (!hit) throw new TypeError("Failed to fetch");
    const r = typeof hit === "function" ? hit(init) : hit;
    return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "Content-Type": "application/json", ...(r.headers ?? {}) } });
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function offline() {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
}

export function setupDom() {
  __resetBackendState();
  localStorage.clear();
  sessionStorage.clear();
  // jsdom has no canvas or object URLs
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
  if (!URL.createObjectURL) (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => "blob:mock";
  if (!URL.revokeObjectURL) (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => undefined;
}

export const META = {
  name: "LogicLens API", version: "2.0.0", auth: "open",
  engines: { configured: "yolo", active: "yolo-onnx", available: { "yolo-onnx": true } },
  ocr: true, llm: { enabled: false, models: {} },
  limits: { upload_mb: 8, max_image_side: 8000, program_chars: 200000, llm_program_chars: 60000, rungs: 2000 },
  platforms: ["rockwell_slc"],
};
export const HEALTH = { status: "ok", version: "2.0.0", auth: "open" };
