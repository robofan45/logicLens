"""Error envelope (contract section 5) and exception handlers.

Every error leaves the API as
``{"error": {"code": "E_...", "message": "...", "request_id": "...", "details": [...]?}}``.
Messages are written for humans and never contain stack traces, file paths or input echoes.
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("logiclens.errors")

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

MAX_DETAILS = 50

_HTTP_CODES = {
    400: ("E_BAD_REQUEST", "The request could not be understood."),
    401: ("E_UNAUTHORIZED", "A valid X-API-Key header is required."),
    403: ("E_FORBIDDEN", "Not allowed."),
    404: ("E_NOT_FOUND", "No such endpoint."),
    405: ("E_METHOD_NOT_ALLOWED", "Method not allowed for this endpoint."),
    413: ("E_TOO_LARGE", "Request body is too large."),
    415: ("E_UNSUPPORTED_MEDIA", "Unsupported media type."),
    429: ("E_RATE_LIMITED", "Too many requests."),
}


class ApiError(Exception):
    """An expected failure with a stable error code. Raise it anywhere; the handler formats it."""

    def __init__(self, status: int, code: str, message: str, details: Optional[List[Any]] = None,
                 headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ApiError({self.status}, {self.code!r}, {self.message!r})"


def error_body(code: str, message: str, request_id: Optional[str] = None,
               details: Optional[List[Any]] = None) -> dict:
    err: Dict[str, Any] = {"code": code, "message": message, "request_id": request_id or request_id_var.get()}
    if details:
        err["details"] = details[:MAX_DETAILS]
    return {"error": err}


def error_response(status: int, code: str, message: str, details: Optional[List[Any]] = None,
                   headers: Optional[Dict[str, str]] = None, request_id: Optional[str] = None) -> JSONResponse:
    return JSONResponse(error_body(code, message, request_id, details), status_code=status, headers=headers)


def _request_id(request: Request) -> str:
    return request.scope.get("state", {}).get("request_id") or request_id_var.get()


def _clean_validation_errors(errors) -> List[dict]:
    """Keep where and why; drop 'input'/'ctx' so user data is never echoed back."""
    out = []
    for e in list(errors)[:MAX_DETAILS]:
        loc = [p for p in e.get("loc", ()) if p != "body"]
        out.append({"loc": [str(p) for p in loc], "msg": str(e.get("msg", "invalid"))[:200],
                    "type": str(e.get("type", "value_error"))[:60]})
    return out


async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return error_response(exc.status, exc.code, exc.message, exc.details, exc.headers, _request_id(request))


async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "E_VALIDATION", "Request validation failed.",
                          _clean_validation_errors(exc.errors()), request_id=_request_id(request))


async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _HTTP_CODES.get(exc.status_code, (f"E_HTTP_{exc.status_code}", "Request failed."))
    headers = dict(exc.headers) if getattr(exc, "headers", None) else None
    return error_response(exc.status_code, code, message, headers=headers, request_id=_request_id(request))


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_handler)  # type: ignore[arg-type]
