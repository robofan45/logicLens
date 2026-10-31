"""LogicLens API: FastAPI app factory and endpoints.

    uvicorn app.main:app --workers 2          (``app`` is built from the environment at import)
    create_app(Settings(...), llm_client=...)  (tests and embedding)

Stateless and zero-retention: uploads are read into memory, decoded, analysed and dropped with
the request. Nothing is written to disk, nothing about the image or program is logged, and there
are no server-side sessions. CPU work (decode, inference, OCR) and LLM calls run in the thread
pool behind per-worker gates, so the event loop never blocks.
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional, Type, TypeVar

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from . import __version__
from .auth import ApiKeyAuth
from .engines import EngineRegistry
from .engines.base import NC
from .errors import ApiError, install_error_handlers
from .gate import Gates
from .imaging import MultipartCollector, Upload, decode_image, quality_metrics, validate_upload
from .llm import AnthropicClient, LLMClient, LLMService
from .middleware import EnvelopeCORSMiddleware, RequestContextMiddleware
from .program import program_from_text
from .ratelimit import RateLimiter, make_backend
from .schemas import PLATFORMS, ChatRequest, ExplainRequest, ImageInfo, Quality, TextRequest
from .settings import Settings
from .vendor.logiclens_ladder import LIMITS

log = logging.getLogger("logiclens.app")

M = TypeVar("M", bound=BaseModel)


def _configure_logging(level: str) -> None:
    logger = logging.getLogger("logiclens")
    logger.setLevel(level)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def _disconnected() -> ApiError:
    return ApiError(400, "E_BAD_REQUEST", "The client disconnected before the request body was complete.")


async def read_upload(request: Request, cap_bytes: int) -> Upload:
    """Stream the multipart body into memory, stopping at the cap whatever Content-Length says."""
    collector = MultipartCollector(request.headers.get("content-type", ""), cap_bytes=cap_bytes)
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > collector.body_cap:
        raise collector.too_large()
    try:
        async for chunk in request.stream():
            collector.feed(chunk)
    except ClientDisconnect:
        raise _disconnected() from None
    return collector.finish()


async def read_json(request: Request, model: Type[M], cap_bytes: int) -> M:
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise ApiError(415, "E_UNSUPPORTED_MEDIA", "Send a JSON body (Content-Type: application/json).")
    too_large = ApiError(413, "E_TOO_LARGE", f"JSON body exceeds {cap_bytes // 1024} KB.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap_bytes:
        raise too_large
    body = bytearray()
    try:
        async for chunk in request.stream():
            body += chunk
            if len(body) > cap_bytes:
                raise too_large
    except ClientDisconnect:
        raise _disconnected() from None
    try:
        return model.model_validate_json(bytes(body))
    except ValidationError as exc:
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        if any(e.get("type") == "json_invalid" for e in errors):
            raise ApiError(400, "E_BAD_REQUEST", "The body is not valid JSON.") from None
        details = [{"loc": [str(p) for p in e.get("loc", ())], "msg": str(e.get("msg", ""))[:200],
                    "type": str(e.get("type", ""))[:60]} for e in errors[:50]]
        raise ApiError(422, "E_VALIDATION", "Request validation failed.", details=details) from None


def _json_body(model: Type[BaseModel]) -> dict:
    return {"requestBody": {"required": True,
                            "content": {"application/json": {"schema": model.model_json_schema()}}}}


_MULTIPART_BODY = {"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
    "type": "object", "required": ["file"],
    "properties": {"file": {"type": "string", "format": "binary", "description": "PNG, JPEG or WEBP"},
                   "platform": {"type": "string", "enum": PLATFORMS}}}}}}}


def create_app(settings: Optional[Settings] = None, *, llm_client: Optional[LLMClient] = None,
               detector_factory=None, ocr=None, redis_client=None) -> FastAPI:
    settings = settings or Settings()
    _configure_logging(settings.log_level)
    gates = Gates.from_settings(settings)
    if llm_client is None and settings.llm_enabled:
        llm_client = AnthropicClient(settings.anthropic_api_key.get_secret_value(), settings.llm_timeout_s,
                                     settings.llm_max_retries)
    engines = EngineRegistry(settings, gates, llm_client=llm_client, detector_factory=detector_factory, ocr=ocr)
    llm = LLMService(settings, llm_client, gates)
    auth = ApiKeyAuth(settings.api_keys)
    limiter = RateLimiter(settings, make_backend(settings, redis_client), auth)
    if not auth.enabled:
        log.warning("LOGICLENS_API_KEYS is not set: the API is open (development mode)")
    if "*" in settings.cors_origins:
        log.warning("LOGICLENS_CORS_ORIGINS contains '*': any website can call this API from a browser")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(engines.warmup)
        yield
        await limiter.close()

    app = FastAPI(title="LogicLens API", version=__version__, lifespan=lifespan,
                  docs_url="/docs" if settings.docs else None, redoc_url=None,
                  openapi_url="/openapi.json" if settings.docs else None)
    app.state.settings = settings
    app.state.gates = gates
    app.state.engines = engines
    app.state.llm = llm
    app.state.limiter = limiter
    install_error_handlers(app)
    app.add_middleware(EnvelopeCORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining",
                                       "X-RateLimit-Reset", "Retry-After"],
                       allow_credentials=False, max_age=600)
    app.add_middleware(RequestContextMiddleware, docs_enabled=settings.docs)

    async def api_rate_limit(request: Request) -> None:
        await limiter.check(request, "api")

    guarded = [Depends(auth), Depends(api_rate_limit)]

    @app.get("/health", tags=["meta"])
    async def health():
        body = {"status": "ok", "version": __version__, "auth": "api_key" if auth.enabled else "open"}
        if not auth.enabled:
            body["warnings"] = ["API keys are not configured: the API is open (development mode)."]
        return body

    app.add_api_route("/health", health, methods=["HEAD"], include_in_schema=False)  # load balancers

    @app.get("/api/meta", tags=["meta"], dependencies=guarded)
    async def meta():
        return {
            "name": "LogicLens API", "version": __version__, "schema_version": "1.0",
            "auth": "api_key" if auth.enabled else "open",
            "engines": {"configured": settings.engine, "active": engines.active_name(),
                        "available": engines.availability()},
            "ocr": engines.ocr is not None,
            "llm": {"enabled": llm.enabled,
                    "models": {"vision": settings.vision_model, "explain": settings.explain_model,
                               "deep": settings.deep_model, "chat": settings.chat_model} if llm.enabled else {}},
            "limits": {"upload_mb": settings.max_upload_mb, "max_image_pixels": settings.max_image_pixels,
                       "max_image_side": settings.max_image_side, "json_body_kb": settings.max_json_kb,
                       "program_chars": LIMITS["program_chars"], "llm_program_chars": settings.llm_max_program_chars,
                       "rungs": LIMITS["rungs"], "rate_limit_per_min": settings.rate_limit_per_min,
                       "llm_rate_limit_per_min": settings.llm_rate_limit_per_min,
                       "rate_limit_shared": limiter.shared},
            "classes": {"count": NC},
            "platforms": PLATFORMS,
        }

    def parse_pipeline(engine, data: bytes, media_type: str, platform: Optional[str]) -> dict:
        t0 = time.perf_counter()
        with gates.cpu.slot():
            image = decode_image(data, media_type, max_pixels=settings.max_image_pixels,
                                 max_side=settings.max_image_side)
            quality = quality_metrics(image)
        decoded = (time.perf_counter() - t0) * 1000
        program = engine.parse(image, platform)
        program.image = ImageInfo(width=image.width, height=image.height, quality=Quality(**quality))
        timing = {"decode": decoded, **(program.timing_ms or {}), "total": (time.perf_counter() - t0) * 1000}
        program.timing_ms = {k: round(max(0.0, v), 1) for k, v in timing.items()}
        return program.to_json()

    @app.post("/api/analyze/parse", tags=["analyze"], dependencies=guarded, openapi_extra=_MULTIPART_BODY)
    async def parse(request: Request):
        engine = engines.select()
        if engine.uses_llm:
            await limiter.check(request, "llm")
        upload = await read_upload(request, settings.upload_cap_bytes)
        platform = upload.fields.get("platform") or None
        if platform is not None and platform not in PLATFORMS:
            raise ApiError(422, "E_VALIDATION", "Unknown platform.",
                           details=[{"loc": ["platform"], "msg": "must be one of: " + ", ".join(PLATFORMS),
                                     "type": "enum"}])
        media_type = validate_upload(upload.file)
        return JSONResponse(await run_in_threadpool(parse_pipeline, engine, upload.file, media_type, platform))

    @app.post("/api/analyze/text", tags=["analyze"], dependencies=guarded, openapi_extra=_json_body(TextRequest))
    async def analyze_text(request: Request):
        body = await read_json(request, TextRequest, settings.json_cap_bytes)
        program = await run_in_threadpool(program_from_text, body.text, body.platform)
        return JSONResponse(program.to_json())

    def require_llm() -> None:
        if not llm.enabled:
            raise ApiError(503, "E_LLM_DISABLED",
                           "AI explanations are not configured on this server (set ANTHROPIC_API_KEY).")

    @app.post("/api/analyze/explain", tags=["ai"], dependencies=guarded, openapi_extra=_json_body(ExplainRequest))
    async def explain(request: Request):
        require_llm()
        await limiter.check(request, "llm")
        body = await read_json(request, ExplainRequest, settings.json_cap_bytes)
        return JSONResponse((await run_in_threadpool(llm.explain, body)).model_dump())

    @app.post("/api/chat", tags=["ai"], dependencies=guarded, openapi_extra=_json_body(ChatRequest))
    async def chat(request: Request):
        require_llm()
        await limiter.check(request, "llm")
        body = await read_json(request, ChatRequest, settings.json_cap_bytes)
        return JSONResponse((await run_in_threadpool(llm.chat, body)).model_dump())

    return app


app = create_app()
