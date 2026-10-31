# LogicLens web app

React 18 + Vite + Tailwind v4. The analysis engine (`src/engine/`) is pure TypeScript and runs
in the browser: parsing, signal trace, 32 checks, corrections, IEC 61131-3 Structured Text and
the scan-cycle simulator need no server and work offline. The backend (`../backend`) is only
used for image recognition and the optional Claude explanations.

## Run

```bash
npm ci
npm run dev            # http://localhost:5173 ; /api and /health are proxied to http://localhost:8000
                       # (override with LOGICLENS_API_TARGET=http://host:port)
npm run build          # type-check + production build in dist/
npm run preview        # serve dist/ (same proxy)
```

With no backend running, the app says so and keeps working for pasted ladder text.
`VITE_API_BASE` (build time) points the app at an API on another origin; leave it empty when
nginx or the dev server proxies `/api`.

## Test (six-gate workflow, gates 1-3)

```bash
npm run test:unit          # engine + library unit tests (Node / jsdom)
npm run test:integration   # parser parity with Python, fuzz, differential ST-vs-simulator, UI flows
npm run coverage           # coverage for src/engine and src/app
npm run typecheck          # app and test sources
```

UI tests run the real router, pages and engine in jsdom with `fetch` mocked at the network
boundary (`tests/helpers/ui.tsx`).

## Layout

```
src/engine/        parse.ts (LLT grammar, contract/README.md), tags.ts, xref.ts (rung-condition
                   trace), sat.ts, faults.ts (32 rules + 19-item checklist), correct.ts,
                   st.ts (Structured Text), simulate.ts, index.ts (analyzeProgram)
src/app/lib/       api.ts (backend client + response validation), history.ts (local, validated),
                   report.ts (escaped Markdown), samples.ts, platforms.ts, rules.ts, useBackend.ts
src/app/components LadderDiagram (SVG from the AST), ProgramEditor, ImagePanel, FaultList,
                   TracePanel, CorrectionsPanel, StPanel, SimulatorPanel, AiPanel, OverviewPanel
src/app/pages/     Home, Analyzer, History, Docs, NotFound
public/            icons, manifest.webmanifest, sw.js (offline shell; never caches /api)
nginx/             production server config + security headers (strict CSP, no inline code)
```

## Security notes

- No `dangerouslySetInnerHTML`; every server or user string renders as text.
- Strict CSP in `nginx/security-headers.conf` (`script-src 'self'; style-src 'self'`, no data:
  fonts); assets are never inlined (`assetsInlineLimit: 0`), fonts are self-hosted.
- API keys live in `sessionStorage` only; requests are sent with `credentials: "omit"`.
- History in `localStorage` is size-capped and re-validated on every read.
- Markdown reports escape user-derived text and fence code with a fence longer than any
  backtick run, so crafted tag names cannot inject links, images or HTML.
- Generated Structured Text sanitises identifiers and comment text (`(*` / `*)` cannot break out).
