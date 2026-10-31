# LogicLens v2

Camera-to-correction for PLC ladder logic. Paste rungs or upload a screenshot, and LogicLens checks
the logic against 32 rules, traces what drives every output, proposes corrections you can review,
exports IEC 61131-3 Structured Text and simulates the scan. Claude explanations are optional.

v2 replaces the v1 Figma Make prototype, which showed the same canned demo results for every
upload. The v1 folders (`AI-Powered PLC Logic Analyzer`, `plc_ladder_logic_dataset`, `LogicLens`) are
untouched.

## What is in the box

| Folder | What | Tests |
|---|---|---|
| `contract/` | The shared language: LogicLens Ladder Text grammar (Rockwell neutral text + IEC aliases), program JSON schema, detector classes, 37 shared parser test vectors, Python reference parser | 72 |
| `web/` | React app + the TypeScript analysis engine (parser, signal trace, 32 checks, corrections, Structured Text, simulator). Runs fully in the browser, works offline, installable (PWA) | 379 |
| `backend/` | FastAPI: image -> ladder text (YOLO ONNX + OCR, Claude vision, or both), Claude explain/chat, API keys, Redis rate limits, hardened uploads, zero retention, Docker | 352 |
| `ml/` | Dataset generator v2 (tight boxes, 6 visual styles, 4 addressing styles, structure labels, augmentation), training/export/eval tools, pilot model `models/logiclens-yolov8n.onnx` | 144 + 3 xfail |
| `samples/` | Your RSLogix 500 screenshot (end-to-end test image) and the v1 outputs | |

## Run it

### On Windows (your PC)

| What you want | Do this | Needs |
|---|---|---|
| A quick look, nothing to install | Double-click **`LogicLens.html`** | A browser |
| The full app, with screenshot recognition | Double-click **`Start-LogicLens.cmd`** | Node.js 20+ and Python 3.11-3.13 (this PC has Node 25 and Python 3.13) |
| Tag names read from screenshots | Install **[Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)**, then close the LogicLens windows and start again | Tesseract. Without it, rungs and instructions are recognised and tag names show as `?` |
| Claude explanations, chat and Claude vision | Set `ANTHROPIC_API_KEY` in your Windows environment variables, then start again | An Anthropic API key |

`LogicLens.html` is the whole app in one file. It does text analysis, all 32 checks, the
signal trace, corrections, Structured Text and the simulator, offline. It has no server, so
screenshot recognition and AI stay off.

`Start-LogicLens.cmd` installs what it needs the first time: web packages (1-2 minutes) and the
API's Python packages (2-5 minutes, in the "LogicLens API" window; leave it open). After that it
starts in seconds. It opens http://localhost:5173 in your browser. Close both LogicLens windows
to stop. Double-clicking it again while LogicLens runs just opens the browser again.

If Windows SmartScreen warns about `Start-LogicLens.cmd` (it does for files unpacked from a
downloaded zip), click **More info → Run anyway**, or right-click the zip → Properties →
**Unblock** before unpacking.

Don't double-click `web/index.html`: that is the source page and it is blank without the dev server.

### By hand (any OS)

```bash
cd web && npm ci && npm run dev                 # http://localhost:5173 (proxies /api to 127.0.0.1:8000)
cd backend && pip install -r requirements.txt   # Python 3.11-3.13, plus tesseract on PATH
LOGICLENS_YOLO_ONNX=../ml/models/logiclens-yolov8n.onnx python -m uvicorn app.main:app --port 8000
docker compose up --build                       # or everything in Docker: http://localhost:8080
```

PowerShell sets variables with `$env:LOGICLENS_YOLO_ONNX = "..\ml\models\logiclens-yolov8n.onnx"`.
The npm scripts call `node node_modules/...` directly on purpose: npm's Windows `.cmd` shims
break in folders whose path contains `&` (like `PLC & Automation`).

Rebuild `LogicLens.html` with `cd web && npm run build:standalone` (output in `web/standalone/`).

## Six-gate report

| Gate | Result |
|---|---|
| 1 Unit | web 340 (engine 98.6 % lines), backend 292 (86 % unit-only, 94 % with integration), ml 128 (84 %), contract 72: all green |
| 2 Integration | web 39 (TS == Python parser on 3 000 inputs; 2 000-program x 200-scan fuzz; generated ST == simulator on 600 random programs; UI flows in jsdom; Windows launcher probe against real HTTP servers), backend 60 (real tesseract, onnxruntime, Redis), ml 16 + 3 documented xfails |
| 3 TDD | Engine, backend and generator written test-first. UI pages were written first and covered after (listed honestly) |
| 4 Security | Scanners: npm audit, pip-audit, bandit, semgrep (OWASP). 24 API probes plus UI/CSP probes (uploads, decompression bombs, CORS, XFF spoofing, auth, ReDoS, XSS, report and ST injection). 27 points: 1 Critical, 3 High, 8 Medium, the rest Low/Info (web 7, backend 6, ml 14) |
| 5 Discuss & fix | Every Critical and High fixed (vitest/tinypool chain, react-router RCE/XSS advisory, vite, Pillow CVEs). Medium: 6 fixed, 1 false positive suppressed with a reason, 1 open (Claude paths need a live-key probe). Scanners re-run: 0 points |
| 6 Load | Text API: 800 users, ~990 req/s, p95 310 ms, 0 errors (no breaking point found in the sandbox). Image recognition: CPU-bound, ~1.8 images/s on 2 cores; p95 1.2 s at 2 users, 2.4 s at 6, 13 s at 14; 0 failed requests (bounded queue + 503 `Retry-After`, client now retries) |

Full reports (findings, status, load runs) live in the `*/.six-gate/` folders of a working copy.
Git ignores them, so they are not published with the repo.

## Measured, not claimed

| What | Number | Where |
|---|---|---|
| Detector, synthetic test split | mAP50 0.891, mAP50-95 0.821 | `ml/models/metrics.json` |
| Your real screenshot (3 rungs) | recognised exactly: all 3 rungs, every operand | `ml/reports/sample_prediction.png` |
| End-to-end on 150 synthetic test images | mnemonic F1 0.84 (0.89 on clean images); operand accuracy 44 %; whole-program exact 2.7 % | `ml/reports/e2e_eval.json` |
| Analysis of a 2 000-rung program | ~0.55 s in the browser | `web/tests/integration/engine/performance.test.ts` |

The detector finds the symbols well; reading the small operand text is the weak link. That is
why recognised programs open in the editor for review, with `?` marking anything unread, and
why the hybrid engine (YOLO boxes + Claude reading) exists.

## Decisions waiting for you

1. **Licensing.** Ultralytics YOLO code and the models it trains are AGPL-3.0. A closed-source
   SaaS needs an Ultralytics Enterprise License, or a permissively licensed detector trained on
   the same generator (the generator does not depend on Ultralytics).
2. **Real training data.** Synthetic data got the pilot to 0.89 mAP50; real HMI photos and IDE
   screenshots with corrected labels are what will move end-to-end accuracy. Every user
   correction in the editor is that data (the Blueprint's flywheel). Collecting it needs consent and storage.
3. **AI layer.** Explain/chat/vision are implemented and tested with a fake client only. Add
   `ANTHROPIC_API_KEY` on a staging server and run the LLM probe set before customers see it.
4. **Billing.** Plans are shown as planned pricing; Stripe is not wired in.
5. **Android.** The v1 APK/AAB source was not in `Downloads\Projects`. v2 is an installable PWA;
   it can be wrapped with Capacitor or a Trusted Web Activity for the Play Store.

## Safety

LogicLens is advisory. It does not certify safety functions (IEC 61508 / IEC 61511) and cannot
see field wiring or hardware configuration. Emergency stops belong in hard-wired or safety-rated
circuits, which is also what the `ESTOP_IN_STANDARD_LOGIC` check tells users.
