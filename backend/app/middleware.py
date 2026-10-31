"""ASGI middleware: request IDs, security headers, access log and the last-resort error envelope.

``RequestContextMiddleware`` is the outermost layer. It catches anything that escaped the
exception handlers and answers 500 E_INTERNAL itself (Starlette's ServerErrorMiddleware would
answer outside every other middleware, so that response would carry no request ID and no
security headers). The traceback goes to the server log only.
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from .errors import error_body, request_id_var

log = logging.getLogger("logiclens.app")
access_log = logging.getLogger("logiclens.access")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

STRICT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Only when LOGICLENS_DOCS=1: FastAPI's Swagger page loads its JS/CSS from jsDelivr and inlines a script.
DOCS_CSP = ("default-src 'none'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: "
            "https://fastapi.tiangolo.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cross-origin-opener-policy": "same-origin",
}
DOCS_PATHS = ("/docs", "/docs/oauth2-redirect")


class RequestContextMiddleware:
    def __init__(self, app, docs_enabled: bool = False):
        self.app = app
        self.docs_enabled = docs_enabled

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        token = request_id_var.set(request_id)
        path = scope.get("path", "")
        csp = DOCS_CSP if self.docs_enabled and path in DOCS_PATHS else STRICT_CSP
        started = False
        status = 500
        t0 = time.perf_counter()

        async def send_wrapper(message):
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                headers["content-security-policy"] = csp
                if "cache-control" not in headers:
                    headers["cache-control"] = "no-store"
                for name, value in (state.get("ratelimit") or {}).items():
                    if name.lower() not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            log.exception("unhandled error (request_id=%s)", request_id)
            if not started:
                response = JSONResponse(error_body("E_INTERNAL", "Internal server error.", request_id),
                                        status_code=500)
                await response(scope, receive, send_wrapper)
        finally:
            access_log.info("%s %s %s %.1fms request_id=%s", scope.get("method", "-"), path, status,
                            (time.perf_counter() - t0) * 1000, request_id)
            request_id_var.reset(token)


class EnvelopeCORSMiddleware(CORSMiddleware):
    """Starlette's CORS middleware, but a rejected preflight answers with the error envelope."""

    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code != 400:
            return response
        headers = {k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")}
        return JSONResponse(error_body("E_CORS_REJECTED",
                                       "Cross-origin request not allowed (origin, method or headers).",
                                       request_id_var.get()), status_code=400, headers=headers)
