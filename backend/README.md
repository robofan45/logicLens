# LogicLens backend

FastAPI service that does the parts of LogicLens that need a server: **vision** (photo or
screenshot of a ladder diagram → LogicLens program), **AI explanations and chat** (Claude),
**API keys** and **quotas**. Signal tracing, rule-based faults, Structured Text and the
simulator run in the browser. The wire format is defined in [`../contract/README.md`](../contract/README.md).

Stateless and zero-retention: see [Zero retention](#zero-retention).

## Run it

### Locally (Python 3.12 or 3.13)

```bash
sudo apt-get install -y tesseract-ocr          # OCR for the YOLO engine (binary only)
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

LOGICLENS_ENGINE=stub uvicorn app.main:app --reload       # fixed demo program, no model, no key
# real engines:
#   LOGICLENS_YOLO_ONNX=../ml/models/<model>.onnx           YOLO + OCR
#   ANTHROPIC_API_KEY=sk-ant-...                            Claude vision + explain + chat
#   both set                                                hybrid (auto)
```

### Docker

```bash
docker compose up --build             # from the repo root: backend + redis
curl -s http://localhost:8000/health
```

Put keys in a `.env` file next to `docker-compose.yml` (never commit it). The YOLO model is read
from `ml/models/` (mounted read-only at `/models`): `LOGICLENS_YOLO_ONNX=/models/<file>.onnx`.
The image is `python:3.12-slim` (digest-pinned), runs as uid 10001 with no pip and no compilers,
and the compose service runs with a read-only root filesystem, a 16 MB tmpfs `/tmp`, all
capabilities dropped and `no-new-privileges`.

### Tests (gates 1-3 of the six-gate workflow)

```bash
pytest -m unit                                   # fast, isolated
pytest -m integration                            # HTTP app, real tesseract, real redis-server, real onnxruntime
pytest --cov=app --cov-report=term-missing       # coverage (94 % of app/ at the time of writing)
pip-audit -r requirements.txt && bandit -r app   # dependency CVEs and static checks
```

There is no Anthropic key in CI: every LLM path runs against `tests/fakes.py::FakeLLM`.
`tests/integration/test_redis_and_model.py` runs the real sample screenshot through a trained
model as soon as `ml/models/*.onnx` exists (skipped until then).

## Configuration

Everything comes from environment variables (no `.env` is read by the app). Invalid values stop
the process at start-up with a validation error.

| Variable | Default | Meaning |
|---|---|---|
| `LOGICLENS_ENGINE` | `auto` | `auto` \| `yolo` \| `claude` \| `hybrid` \| `stub`. `auto` = hybrid if a model and a key are configured, else whichever exists; `stub` only when set explicitly. |
| `LOGICLENS_YOLO_ONNX` | unset | Path to a YOLOv8 ONNX detector exported with `contract/classes.json` (output `[1, 48, N]`). |
| `LOGICLENS_YOLO_CONF` | `0.25` | Detection confidence threshold. |
| `LOGICLENS_YOLO_IOU` | `0.45` | Class-wise NMS IoU threshold. |
| `LOGICLENS_YOLO_IMGSZ` | `640` | Input size used when the model's input shape is dynamic. |
| `LOGICLENS_YOLO_THREADS` | `1` | onnxruntime intra-op threads per session (0 = ORT default). |
| `LOGICLENS_OCR` | `true` | Read operands with tesseract (off: operands are `?`). |
| `LOGICLENS_OCR_PASSES` | `5` | Preprocessing variants voted per operand, 1-5 (accuracy vs CPU; see below). |
| `LOGICLENS_TESSERACT_CMD` | `tesseract` | Tesseract binary. |
| `LOGICLENS_OCR_TIMEOUT_S` | `20` | Per tesseract call. |
| `ANTHROPIC_API_KEY` (or `LOGICLENS_ANTHROPIC_API_KEY`) | unset | Enables Claude vision, explain and chat. |
| `LOGICLENS_VISION_MODEL` | `claude-sonnet-5-5` | Model for image transcription. |
| `LOGICLENS_EXPLAIN_MODEL` | `claude-sonnet-5-5` | Model for `/api/analyze/explain`. |
| `LOGICLENS_DEEP_MODEL` | `claude-opus-5-5` | Model for explain with `"depth": "deep"`. |
| `LOGICLENS_CHAT_MODEL` | `claude-sonnet-5-5` | Model for `/api/chat` (`claude-haiku-5-5` is the cheap option). |
| `LOGICLENS_LLM_TIMEOUT_S` | `60` | Per Claude call (vision allows one repair call within 2x this). |
| `LOGICLENS_LLM_MAX_RETRIES` | `1` | SDK retries on 429/5xx/connection errors. |
| `LOGICLENS_VISION_MAX_TOKENS` / `_EXPLAIN_` / `_CHAT_` | `8192` / `4096` / `1500` | Output token caps. |
| `LOGICLENS_LLM_MAX_PROGRAM_CHARS` | `60000` | Cost guard: longer programs get 413 on explain/chat. |
| `LOGICLENS_LLM_CONCURRENCY` / `LOGICLENS_LLM_QUEUE` | `4` / `16` | Concurrent Claude calls per worker / callers allowed to wait. |
| `LOGICLENS_MAX_UPLOAD_MB` | `8` | Upload cap, enforced while streaming (Content-Length is not trusted). |
| `LOGICLENS_MAX_IMAGE_PIXELS` | `40000000` | Decoded pixel cap (decompression-bomb guard). |
| `LOGICLENS_MAX_IMAGE_SIDE` | `8000` | Max width or height in px. |
| `LOGICLENS_MAX_JSON_KB` | `256` | JSON body cap. |
| `LOGICLENS_INFERENCE_CONCURRENCY` | `1` | Concurrent decode/YOLO/OCR jobs per worker. |
| `LOGICLENS_INFERENCE_QUEUE` | `8` | Jobs allowed to wait for a slot; more get 503 `E_BUSY` at once. |
| `LOGICLENS_QUEUE_TIMEOUT_S` | `15` | Longest wait for a slot before 503 `E_BUSY`. |
| `LOGICLENS_CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allow-list (`scheme://host[:port]`). Credentials are never allowed. |
| `LOGICLENS_API_KEYS` | unset | Comma-separated keys (>= 16 chars) for the `X-API-Key` header. Unset = open API (development). |
| `LOGICLENS_DOCS` | `false` | Serve `/docs` and `/openapi.json` (Swagger loads JS from jsDelivr; keep off in production). |
| `REDIS_URL` (or `LOGICLENS_REDIS_URL`) | unset | Shared rate-limit counters. Unset = in-memory, **per worker process**. |
| `LOGICLENS_RATE_LIMIT_PER_MIN` | `60` | Requests per minute per client on `/api/*` (0 = off). |
| `LOGICLENS_LLM_RATE_LIMIT_PER_MIN` | `10` | Stricter budget for requests that call Claude (0 = off). |
| `LOGICLENS_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |
| `WEB_CONCURRENCY` | `2` (Docker) | uvicorn worker processes. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies trusted for `X-Forwarded-For` (rate limits key on the client IP). |

## Endpoints

All errors use the contract envelope
`{"error": {"code": "E_...", "message": "...", "request_id": "...", "details": [...]?}}`.
When `LOGICLENS_API_KEYS` is set, every `/api/*` route needs `-H "X-API-Key: $KEY"`.

```bash
curl -s localhost:8000/health                                   # always open; says whether the API is open
curl -s localhost:8000/api/meta                                 # version, engines, LLM, limits (no secrets)

curl -s -F file=@../samples/ladder_logic_program_PLC1.webp -F platform=rockwell_slc \
     localhost:8000/api/analyze/parse                            # image -> program JSON (program.schema.json)

curl -s -H 'Content-Type: application/json' localhost:8000/api/analyze/text \
     -d '{"text": "XIC(Start)[XIC(Motor),XIC(Remote)]XIO(Stop)OTE(Motor);"}'

curl -s -H 'Content-Type: application/json' localhost:8000/api/analyze/explain \
     -d '{"program_text": "XIC(Start)XIO(Stop)OTE(Motor);", "platform": "rockwell_logix",
          "user_context": "conveyor 3", "findings": [], "depth": "standard"}'

curl -s -H 'Content-Type: application/json' localhost:8000/api/chat \
     -d '{"program_text": "XIC(Start)XIO(Stop)OTE(Motor);", "question": "What stops the motor?",
          "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}'
```

| Endpoint | Success | Notes |
|---|---|---|
| `GET /health` (and `HEAD`) | `{status, version, auth, warnings?}` | Never authenticated or rate limited. |
| `GET /api/meta` | engines (configured/active/available), `ocr`, `llm` (enabled, model IDs), limits, class count, platforms | |
| `POST /api/analyze/parse` | Program JSON, `source:"image"`, `image.quality` 0-100, `timing_ms` | multipart `file` (PNG/JPEG/WEBP) + optional `platform`. Counts against the LLM budget when the active engine uses Claude. |
| `POST /api/analyze/text` | Program JSON, `source:"text"`, `engine.name:"text"` | Platform guessed from addressing style when not given. |
| `POST /api/analyze/explain` | `{summary, rung_explanations, ai_findings, model, disclaimer}` | `depth:"deep"` uses `LOGICLENS_DEEP_MODEL`. |
| `POST /api/chat` | `{answer, model, disclaimer}` | Stateless: the client sends `history` (max 20 turns). |

| Status | Code | When |
|---|---|---|
| 400 | `E_BAD_REQUEST` | Malformed multipart or JSON, client disconnected mid-body |
| 400 | `E_CORS_REJECTED` | CORS preflight from a non-allowed origin, method or header |
| 401 | `E_UNAUTHORIZED` | Missing or wrong `X-API-Key` |
| 404 / 405 | `E_NOT_FOUND` / `E_METHOD_NOT_ALLOWED` | |
| 413 | `E_TOO_LARGE` | Upload, JSON body or program (for the LLM) over its cap |
| 415 | `E_UNSUPPORTED_MEDIA` | Not PNG/JPEG/WEBP by magic bytes (SVG, PDF, GIF...), polyglot, wrong content type |
| 422 | `E_VALIDATION` | Request fields (`details` lists `loc`/`msg`, never the input) |
| 422 | `E_BAD_IMAGE` | Corrupt or truncated image, too many pixels, side too long, decompression bomb |
| 422 | `E_LADDER_SYNTAX` | LLT parse errors; `details` = the parser's `{code, message, line, col}` list |
| 429 | `E_RATE_LIMITED` | Budget exhausted; `Retry-After` and `X-RateLimit-*` headers |
| 500 | `E_INTERNAL` | Bug; traceback in the server log only |
| 502 | `E_ENGINE_FAILED` / `E_LLM_FAILED` | Claude returned unusable output twice, or the provider rejected the call |
| 503 | `E_ENGINE_UNAVAILABLE` | No vision engine configured (message says which variable to set) or the model failed to load |
| 503 | `E_LLM_DISABLED` | Explain/chat without `ANTHROPIC_API_KEY` |
| 503 | `E_BUSY` | Worker's inference/LLM queue full or timed out, or Anthropic overloaded; `Retry-After` |
| 504 | `E_UPSTREAM_TIMEOUT` | Claude did not answer in time |

## Engines

* **yolo** (`app/engines/yolo_onnx.py`, `assembler.py`, `ocr.py`). One onnxruntime CPU session per
  worker, loaded at start-up. Letterbox to the model input, decode Ultralytics `[1, 4+nc, N]`
  (or its transpose), class-wise NMS, map to `classes.json`. The assembler follows contract §6:
  rows by y (gap clustering, so a slightly tilted photo stays one rung), branch connectors paired by
  overlap, nested branches, parallel outputs, connector-less lower rows attached by layout (with a
  warning), operands read above contacts/coils (RSLogix 500 split `I:1` + `1` → `I:1/1`) and inside
  box instructions (`Timer`, `Preset`, `Source A`...). Unreadable operands become `?` and lower the
  confidence; every rung is re-parsed with the vendored contract parser or dropped with a warning.
  OCR: crops are batched into one image per pass and piped to the tesseract **binary over
  stdin/stdout** (pytesseract writes temp files, so it is not used). Measured on the hand-labelled
  PLC1 screenshot with ±3 px box jitter (12 runs, 120 operands, 2-core sandbox):

  | `LOGICLENS_OCR_PASSES` | operands exact | rungs exact | OCR time / image |
  |---|---|---|---|
  | 1 | 93 % | 28/36 | 0.29 s |
  | 3 | 96 % | 31/36 | 0.58 s |
  | 5 (default) | 100 % | 36/36 | 0.96 s |
* **claude** (`claude_vision.py`). The image is downscaled to ≤ 1568 px / 1.15 MP and sent as a PNG
  (JPEG if large); the reply must be one JSON object whose rungs are LLT. Pydantic validation plus the
  parser; one repair round with the parser's errors; then 502. Element boxes are mapped back to
  source pixels.
* **hybrid** (`hybrid.py`). YOLO first, then Claude with the detections as escaped hints; Claude's
  text, YOLO's boxes. If Claude fails or is busy, the YOLO + OCR result is returned
  (`engine.name: "yolo-onnx"` + warning); if the detector fails, Claude runs without hints.
* **stub** (`stub.py`). The PLC1 ground truth, every time. For tests, demos and load tests only.

## Security model

* **Auth**: optional API keys in `X-API-Key`, compared as SHA-256 digests with `hmac.compare_digest`
  against every key. `/health` is always open and reports whether auth is on. Rate limits key on the
  API key fingerprint when auth is on (so rotating fake keys cannot dodge per-IP limits when it is off).
* **CORS**: explicit allow-list, `GET`/`POST` only, `Content-Type`/`X-API-Key`/`X-Request-ID`
  headers, never credentials. Rejected preflights get the error envelope.
* **Headers on every response**: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin`,
  `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; ...`, `Cache-Control: no-store`,
  `X-Request-ID` (client value echoed only if it matches `[A-Za-z0-9._-]{8,64}`). HSTS belongs on the
  TLS terminator.
* **Uploads**: size cap enforced while streaming; magic-byte allow-list (PNG/JPEG/WEBP); polyglot checks
  (markup or `%PDF-` in the first KB, any data after PNG `IEND` or past the WEBP RIFF size,
  archive/markup after JPEG EOI); Pillow restricted to the sniffed format; dimension and pixel caps
  checked from the header before decompression; truncated files rejected.
* **Bodies**: JSON capped at 256 KB before parsing; LLT goes through the contract parser limits
  (200 000 chars, 2 000 rungs, ...); validation errors never echo input.
* **Resource limits**: per-worker gates for CPU work and LLM calls with bounded queues and timeouts
  (503 `E_BUSY`), so a burst cannot queue unbounded images in memory. The event loop never runs
  CPU work.
* **LLM**: everything the user sends (program text, comments, tag names, context, findings,
  questions, text inside images) is data: delimited, `<`/`>` escaped, and the system prompts forbid
  following instructions found in it. Output is parsed, validated, length-clipped and re-parsed;
  `model` and `disclaimer` are always set by the server; a program that touches safety functions
  (E-stop, guards, interlocks, MCR...) always carries
  `[SAFETY-CRITICAL: Requires independent verification per IEC 61508/61511]`.
* **Errors**: stable codes, human messages, request ID; no stack traces, file paths or upstream
  error details in responses. `/api/meta` exposes no secrets.
* **Rate limiting**: fixed one-minute windows, `api` and stricter `llm` budgets, `X-RateLimit-*`
  headers. With `REDIS_URL` the counters are shared by all workers and replicas; if Redis fails the
  limiter falls back to per-process counting (logged). **Without Redis the limits are per worker
  process**: with `WEB_CONCURRENCY=2` a client effectively gets twice the budget.
* **Container**: non-root, no pip/compilers, digest-pinned base, read-only root FS in compose.

## Zero retention

Uploaded images are read into memory in chunks, decoded from a `BytesIO`, analysed and released when
the request ends. They are never written to disk (the multipart parser keeps parts in memory; OCR
crops go to tesseract over a pipe), never logged (the access log records method, path, status,
duration and request ID only; no bodies, filenames, query strings or client IPs), and never sent
anywhere except to Anthropic when a Claude engine is configured (Anthropic's API data-retention
terms then apply). There are no server-side sessions or histories: chat history lives in the
client and is sent with each request. Redis holds only rate-limit counters keyed by a hashed API key
or the client IP, expiring after ~65 s, with persistence disabled.
