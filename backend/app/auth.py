"""Optional API keys (LOGICLENS_API_KEYS, comma-separated) sent in the X-API-Key header.

When no keys are configured the API is open (development) and /health says so. /health is always
open. Keys are compared as SHA-256 digests with hmac.compare_digest against every configured key,
so neither timing nor the number of keys leaks which key (or how much of it) matched.
"""
from __future__ import annotations

import hashlib
import hmac
from typing import Optional, Sequence

from fastapi import Request
from pydantic import SecretStr

from .errors import ApiError

MAX_KEY_CHARS = 512


class ApiKeyAuth:
    def __init__(self, keys: Sequence[SecretStr]):
        self._digests = [hashlib.sha256(k.get_secret_value().encode("utf-8")).digest() for k in keys]

    @property
    def enabled(self) -> bool:
        return bool(self._digests)

    def verify(self, presented: Optional[str]) -> bool:
        if not self.enabled:
            return True
        if not presented or len(presented) > MAX_KEY_CHARS:
            presented = ""
        digest = hashlib.sha256(presented.encode("utf-8", "replace")).digest()
        ok = False
        for known in self._digests:
            ok |= hmac.compare_digest(digest, known)
        return ok and bool(presented)

    @staticmethod
    def fingerprint(presented: str) -> str:
        """A stable, non-reversible id for rate limiting and logs."""
        return hashlib.sha256(presented.encode("utf-8", "replace")).hexdigest()[:16]

    async def __call__(self, request: Request) -> None:
        if not self.verify(request.headers.get("x-api-key")):
            raise ApiError(401, "E_UNAUTHORIZED", "Missing or invalid X-API-Key header.",
                           headers={"WWW-Authenticate": 'ApiKey realm="logiclens", header="X-API-Key"'})
