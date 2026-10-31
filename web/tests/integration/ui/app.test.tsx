// @vitest-environment jsdom
// Integration tests: the real app (router, pages, engine) in a DOM, with the backend mocked at fetch.
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HEALTH, META, mockFetch, offline, renderAt, setupDom } from "../../helpers/ui";

const SAMPLE_PARSE = {
  schema_version: "1.0",
  source: "image",
  platform: "rockwell_slc",
  rungs: [
    { number: 0, text: "XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);", confidence: 93, elements: [{ index: 0, mnemonic: "XIC", bbox: [10, 10, 30, 30], confidence: 90 }] },
    { number: 1, text: "[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);", confidence: 91 },
    { number: 2, text: "XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);", confidence: 90 },
  ],
  detections: [],
  image: { width: 892, height: 508, quality: { overall: 100, blur: 100, contrast: 100 } },
  warnings: [],
  engine: { name: "yolo-onnx", version: "2.0.0" },
  timing_ms: { total: 512 },
};

beforeEach(() => setupDom());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const editor = () => screen.getByRole("textbox", { name: "Ladder text" }) as HTMLTextAreaElement;

async function analysed() {
  // the sample auto-runs; wait until the results tablist exists
  return screen.findByRole("tablist", { name: "Results" }, { timeout: 5000 });
}

describe("analyzer", () => {
  it("runs the faulty demo end to end and shows real findings", async () => {
    offline();
    renderAt("/analyzer?sample=faulty-demo");
    const tabs = await analysed();
    expect(screen.getByText(/Risk score/i)).toBeTruthy();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Findings/ }));
    expect(await screen.findByText("MOTOR_OUT is driven by 2 coils")).toBeTruthy();
    expect(screen.getByText(/Emergency stop handled in standard PLC logic/)).toBeTruthy();
    // the history got the run
    expect(JSON.parse(localStorage.getItem("logiclens.history.v1")!)).toHaveLength(1);
  });

  it("locates a finding in the diagram", async () => {
    offline();
    renderAt("/analyzer?sample=faulty-demo");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Findings/ }));
    await userEvent.click(screen.getAllByRole("button", { name: /Show ".*" in the ladder diagram/ })[0]);
    expect(within(tabs).getByRole("tab", { name: "Diagram" }).getAttribute("aria-selected")).toBe("true");
    expect(await screen.findByText(/Power reaches it when/)).toBeTruthy();
  });

  it("shows parse errors with line and column while typing", async () => {
    offline();
    renderAt("/analyzer");
    const box = editor();
    fireEvent.change(box, { target: { value: "XIC(A)OTE(B);\nFOO(X)OTE(Y);" } });
    expect(await screen.findByText(/Line 2, col 1: unknown instruction 'FOO'/)).toBeTruthy();
  });

  it("renders hostile tag names as text, never as markup", async () => {
    offline();
    renderAt("/analyzer");
    const box = editor();
    fireEvent.change(box, { target: { value: 'XIC("<img src=x onerror=alert(1)>")OTE(Out);' } });
    await userEvent.click(screen.getByRole("button", { name: "Analyse" }));
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Signal trace/ }));
    expect(document.querySelector('img[src="x"]')).toBeNull();
    expect(screen.getAllByText(/<img src=x onerror=alert\(1\)>/).length).toBeGreaterThan(0);
  });

  it("applies suggested corrections and re-analyses", async () => {
    offline();
    renderAt("/analyzer");
    fireEvent.change(editor(), { target: { value: "XIC(Start_PB)XIO(Stop_PB)OTE(Motor);\nXIC(Remote)OTE(Motor);" } });
    await userEvent.click(screen.getByRole("button", { name: "Analyse" }));
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Corrections/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Load corrected program into the editor/ }));
    await waitFor(() => expect((editor()).value).toMatch(/\[/));
    await userEvent.click(within(await analysed()).getByRole("tab", { name: /Findings/ }));
    expect(screen.queryByText(/is driven by 2 coils/)).toBeNull();
  });

  it("simulates a seal-in: start latches the motor, the NC stop drops it", async () => {
    offline();
    renderAt("/analyzer?sample=motor");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Simulator/ }));
    const scan = () => userEvent.click(screen.getByRole("button", { name: /One scan/ }));
    const motor = () => within(screen.getByRole("region", { name: "Outputs and internal tags" })).getByText("Motor_Run").parentElement!;
    await scan();
    expect(motor().textContent).toMatch(/off/);
    const start = screen.getByRole("button", { name: /^Start_PB/ });
    await userEvent.click(start); // actuate
    await scan();
    await userEvent.click(start); // release
    await scan();
    expect(motor().textContent).toMatch(/ON/);
    const stop = screen.getByRole("button", { name: /^Stop_PB/ });
    await userEvent.click(stop); // press the NC stop: bit goes to 0
    await scan();
    expect(motor().textContent).toMatch(/off/);
  });

  it("explains why AI is unavailable instead of failing", async () => {
    offline();
    renderAt("/analyzer?sample=motor");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /AI explain/ }));
    expect(await screen.findByText(/AI explanations are not available right now/)).toBeTruthy();
  });

  it("keyboard: arrow keys move between result tabs", async () => {
    offline();
    renderAt("/analyzer?sample=motor");
    const tabs = await analysed();
    const overview = within(tabs).getByRole("tab", { name: /Overview/ });
    overview.focus();
    fireEvent.keyDown(overview, { key: "ArrowRight" });
    expect(within(tabs).getByRole("tab", { name: "Diagram" }).getAttribute("aria-selected")).toBe("true");
  });
});

describe("image recognition", () => {
  const file = () => new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "plc.png", { type: "image/png" });

  it("uploads, shows the recognised rungs, and analyses them after review", async () => {
    const { calls } = mockFetch({
      "/health": { body: HEALTH },
      "/api/meta": { body: META },
      "/api/analyze/parse": { body: SAMPLE_PARSE },
    });
    renderAt("/analyzer");
    await userEvent.click(screen.getByRole("tab", { name: "Image" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file());
    await userEvent.click(await screen.findByRole("button", { name: /Recognise ladder logic/ }));
    expect(await screen.findByText(/3 rungs recognised/)).toBeTruthy();
    const parseCall = calls.find((c) => c.url.endsWith("/api/analyze/parse"))!;
    expect(parseCall.init?.body).toBeInstanceOf(FormData);
    await userEvent.click(screen.getByRole("button", { name: /Review in editor and analyse/ }));
    await analysed();
    expect((editor()).value).toContain("0001: [XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);");
  });

  it("warns loudly when the server runs the stub engine", async () => {
    mockFetch({
      "/health": { body: HEALTH },
      "/api/meta": { body: META },
      "/api/analyze/parse": { body: { ...SAMPLE_PARSE, engine: { name: "stub" } } },
    });
    renderAt("/analyzer");
    await userEvent.click(screen.getByRole("tab", { name: "Image" }));
    await userEvent.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file());
    await userEvent.click(await screen.findByRole("button", { name: /Recognise ladder logic/ }));
    expect(await screen.findByText(/fixed demo program, not a reading of your image/)).toBeTruthy();
  });

  it("rejects non-image files before uploading", async () => {
    const { calls } = mockFetch({ "/health": { body: HEALTH }, "/api/meta": { body: META } });
    renderAt("/analyzer");
    await userEvent.click(screen.getByRole("tab", { name: "Image" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["<svg/>"], "x.svg", { type: "image/svg+xml" })] } });
    expect(await screen.findByText(/Use a PNG, JPEG or WEBP image/)).toBeTruthy();
    expect(calls.some((c) => c.url.includes("/api/analyze/parse"))).toBe(false);
  });

  it("explains an offline server and keeps text analysis available", async () => {
    offline();
    renderAt("/analyzer");
    await userEvent.click(screen.getByRole("tab", { name: "Image" }));
    expect(await screen.findByText(/server is not reachable/)).toBeTruthy();
  });

  it("maps server errors to friendly messages", async () => {
    mockFetch({
      "/health": { body: HEALTH },
      "/api/meta": { body: META },
      "/api/analyze/parse": { status: 422, body: { error: { code: "E_BAD_IMAGE", message: "decompression bomb", request_id: "x" } } },
    });
    renderAt("/analyzer");
    await userEvent.click(screen.getByRole("tab", { name: "Image" }));
    await userEvent.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file());
    await userEvent.click(await screen.findByRole("button", { name: /Recognise ladder logic/ }));
    expect(await screen.findByText(/could not be decoded/)).toBeTruthy();
  });
});

describe("history and navigation", () => {
  it("lists saved analyses, reopens one and deletes it", async () => {
    offline();
    const view = renderAt("/analyzer?sample=conveyor");
    await analysed();
    await act(() => view.router.navigate("/history"));
    const link = await screen.findByRole("link", { name: /Conveyor with start warning/ });
    await userEvent.click(link);
    await analysed();
    expect((editor()).value).toContain("Start_Delay");
    await act(() => view.router.navigate("/history"));
    await userEvent.click(await screen.findByRole("button", { name: /Delete Conveyor/ }));
    expect(await screen.findByText(/No analyses yet/)).toBeTruthy();
  });

  it("shows an empty history when storage is corrupted", async () => {
    offline();
    localStorage.setItem("logiclens.history.v1", "]]]not json");
    renderAt("/history");
    expect(await screen.findByText(/No analyses yet/)).toBeTruthy();
  });

  it("renders home, docs and a 404 page", async () => {
    offline();
    const view = renderAt("/");
    expect(await screen.findByRole("heading", { level: 1, name: /Find the fault/ })).toBeTruthy();
    await act(() => view.router.navigate("/docs"));
    expect(await screen.findByRole("heading", { name: /Checks \(32\)/ })).toBeTruthy();
    await act(() => view.router.navigate("/nope"));
    expect(await screen.findByText(/Page not found/)).toBeTruthy();
  });
});

describe("AI explain (backend with an LLM)", () => {
  const llmMeta = { ...META, llm: { enabled: true, models: { explain: "claude-sonnet-5-5" } } };

  it("sends program + findings, renders the answer as plain text, and chats", async () => {
    const { calls } = mockFetch({
      "/health": { body: HEALTH },
      "/api/meta": { body: llmMeta },
      "/api/analyze/explain": {
        body: {
          summary: "Motor seal-in circuit. <img src=y onerror=alert(2)>",
          rung_explanations: [{ rung: 0, text: "Start latches the motor." }],
          ai_findings: [{ severity: "medium", title: "Consider a run-feedback contact", rungs: [0], description: "Use the contactor aux.", recommendation: "Add XIC(Run_FB)." }],
          model: "claude-sonnet-5-5",
          disclaimer: "Advisory only.",
        },
      },
      "/api/chat": { body: { answer: "Stop_PB opens the rung.", model: "claude-sonnet-5-5", disclaimer: "Advisory only." } },
    });
    renderAt("/analyzer?sample=motor");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /AI explain/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Explain this program/ }));
    expect(await screen.findByText(/Consider a run-feedback contact/)).toBeTruthy();
    expect(document.querySelector('img[src="y"]')).toBeNull();
    const body = JSON.parse(String(calls.find((c) => c.url.endsWith("/api/analyze/explain"))!.init!.body));
    expect(body.program_text).toContain("OTE(Motor_Run)");
    expect(body.platform).toBe("rockwell_logix");
    expect(Array.isArray(body.findings)).toBe(true);
    await userEvent.type(screen.getByRole("textbox", { name: "Question about the program" }), "What stops the motor?");
    await userEvent.click(screen.getByRole("button", { name: "Send question" }));
    expect(await screen.findByText("Stop_PB opens the rung.")).toBeTruthy();
  });

  it("surfaces LLM errors without breaking the page", async () => {
    mockFetch({
      "/health": { body: HEALTH },
      "/api/meta": { body: llmMeta },
      // Retry-After beyond the client's wait cap: surfaced at once instead of retried
      "/api/analyze/explain": { status: 503, body: { error: { code: "E_BUSY", message: "busy", request_id: "r" } }, headers: { "Retry-After": "30" } },
    });
    renderAt("/analyzer?sample=motor");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /AI explain/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Explain this program/ }));
    expect(await screen.findByText(/The server is busy/)).toBeTruthy();
  });
});

describe("exports", () => {
  it("shows Structured Text and downloads .st, .md and .json files", async () => {
    offline();
    const created: Blob[] = [];
    URL.createObjectURL = ((b: Blob) => { created.push(b); return "blob:x"; }) as typeof URL.createObjectURL;
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderAt("/analyzer?sample=conveyor");
    const tabs = await analysed();
    await userEvent.click(within(tabs).getByRole("tab", { name: /Structured Text/ }));
    expect(screen.getByLabelText("Generated Structured Text").textContent).toMatch(/PROGRAM/);
    await userEvent.click(screen.getByRole("button", { name: ".st" }));
    await userEvent.click(screen.getByRole("button", { name: /Report \(\.md\)/ }));
    await userEvent.click(screen.getByRole("button", { name: /JSON/ }));
    expect(clicks).toHaveBeenCalledTimes(3);
    const readBlob = (b: Blob) => new Promise<string>((resolve) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.readAsText(b); });
    const json = JSON.parse(await readBlob(created[2]));
    expect(json.tool).toBe("LogicLens");
    expect(json.findings).toBeInstanceOf(Array);
    expect(await readBlob(created[1])).toMatch(/^# LogicLens analysis/);
  });
});
