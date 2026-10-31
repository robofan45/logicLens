// Start-LogicLens.cmd asks scripts/launcher-probe.mjs "is LogicLens already running?" before it
// starts anything, so a second double-click reuses the running copy. Real HTTP servers, real node.
import { execFile } from "node:child_process";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

const PROBE = path.resolve(__dirname, "../../../scripts/launcher-probe.mjs");
const servers: Server[] = [];

function probe(kind: "web" | "api", url: string): Promise<number> {
  return new Promise((resolve) => {
    execFile(
      process.execPath,
      [PROBE, kind],
      { env: { ...process.env, LOGICLENS_PROBE_URL: url }, timeout: 20_000 },
      (err) => resolve(err ? (typeof err.code === "number" ? err.code : -1) : 0),
    );
  });
}

async function serve(handler: (req: IncomingMessage, res: ServerResponse) => void): Promise<string> {
  const server = createServer(handler);
  servers.push(server);
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
}

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map((s) => new Promise<void>((r) => { s.closeAllConnections(); s.close(() => r()); })),
  );
});

describe("launcher probe", () => {
  it("web: the LogicLens page answers -> 0 (reuse it)", async () => {
    const url = await serve((_, res) => res.end("<title>LogicLens · PLC ladder logic analyzer</title>"));
    expect(await probe("web", url)).toBe(0);
  });

  it("web: another app owns the port -> 2", async () => {
    const url = await serve((_, res) => res.end("<title>Some other Vite app</title>"));
    expect(await probe("web", url)).toBe(2);
  });

  it("nothing listening -> 1 (start it)", async () => {
    const url = await serve((_, res) => res.end("x"));
    const s = servers.pop()!;
    await new Promise<void>((r) => s.close(() => r()));
    expect(await probe("web", url)).toBe(1);
    expect(await probe("api", url)).toBe(1);
  });

  it("api: LogicLens /health JSON -> 0", async () => {
    const url = await serve((_, res) => {
      res.setHeader("content-type", "application/json");
      res.end(JSON.stringify({ status: "ok", version: "2.0.0", auth: "open" }));
    });
    expect(await probe("api", url)).toBe(0);
  });

  it("api: a non-LogicLens answer on port 8000 -> 2", async () => {
    const html = await serve((_, res) => res.end("<html>admin console</html>"));
    expect(await probe("api", html)).toBe(2);
    const json = await serve((_, res) => res.end(JSON.stringify({ ok: true })));
    expect(await probe("api", json)).toBe(2);
  });

  it("a server that accepts but never answers -> 2 after the 3 s timeout", async () => {
    const url = await serve(() => { /* never respond */ });
    const t0 = Date.now();
    expect(await probe("web", url)).toBe(2);
    expect(Date.now() - t0).toBeLessThan(10_000);
  });
});
