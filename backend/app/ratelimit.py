"""Fixed-window rate limiting per client: the API key when keys are configured, else the client IP.

Two budgets per minute: ``api`` for every /api request and a stricter ``llm`` budget for requests
that call Claude (explain, chat, and parse when the active engine uses Claude).

Backends:
  * Redis (REDIS_URL set): counters shared by every worker and replica (INCR + EXPIRE in a
    MULTI). If Redis fails, the request is counted by the in-memory backend instead (logged), so
    a Redis outage degrades limits to per-process rather than switching them off.
  * In-memory: per worker process only. With N workers a client effectively gets N times the
    configured budget, so production deployments should set REDIS_URL.

The client IP is ``request.client.host``. Behind a reverse proxy, run uvicorn with
``--proxy-headers`` and ``FORWARDED_ALLOW_IPS=<proxy ip>`` so that is the real client address.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from .auth import ApiKeyAuth
from .errors import ApiError

log = logging.getLogger("logiclens.ratelimit")

WINDOW_S = 60


@dataclass
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_s: int


def _decision(count: int, limit: int, window_start: float, window: int, now: float) -> Decision:
    reset = max(1, int(math.ceil(window_start + window - now)))
    return Decision(count <= limit, limit, max(0, limit - count), reset)


class MemoryBackend:
    """Per-process counters; bounded so a flood of distinct clients cannot grow memory without limit."""

    def __init__(self, clock: Callable[[], float] = time.time, max_keys: int = 100_000):
        self.clock = clock
        self.max_keys = max_keys
        self._counts: Dict[str, Tuple[float, int]] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._counts)

    async def hit(self, key: str, limit: int, window: int) -> Decision:
        now = self.clock()
        start = (now // window) * window
        with self._lock:
            prev_start, count = self._counts.get(key, (start, 0))
            if prev_start != start:
                count = 0
            count += 1
            self._counts[key] = (start, count)
            if len(self._counts) > self.max_keys:
                self._counts = {k: v for k, v in self._counts.items() if v[0] == start}
                if len(self._counts) > self.max_keys:  # still too many in this window: drop the oldest
                    for k in list(self._counts)[: len(self._counts) - self.max_keys]:
                        del self._counts[k]
        return _decision(count, limit, start, window, now)


class RedisBackend:
    def __init__(self, client, fallback: MemoryBackend, clock: Callable[[], float] = time.time,
                 prefix: str = "logiclens:rl:"):
        self.client = client
        self.fallback = fallback
        self.clock = clock
        self.prefix = prefix
        self._last_warning = 0.0

    async def hit(self, key: str, limit: int, window: int) -> Decision:
        now = self.clock()
        start = (now // window) * window
        rkey = f"{self.prefix}{key}:{int(start)}"
        try:
            async with self.client.pipeline(transaction=True) as pipe:
                pipe.incr(rkey)
                pipe.expire(rkey, window + 5)
                count, _ = await pipe.execute()
        except Exception as exc:  # any Redis/network failure: degrade to per-process limits
            if now - self._last_warning > 60:
                log.warning("Redis rate limiting failed (%s); using the in-memory limiter", type(exc).__name__)
                self._last_warning = now
            return await self.fallback.hit(key, limit, window)
        return _decision(int(count), limit, start, window, now)

    async def close(self) -> None:
        close = getattr(self.client, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception as exc:  # pragma: no cover - best effort at shutdown
                log.debug("closing the Redis client failed: %s", type(exc).__name__)


def make_backend(settings, redis_client=None):
    memory = MemoryBackend()
    if redis_client is None and settings.redis_url is not None:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(settings.redis_url.get_secret_value(), socket_timeout=0.5,
                                         socket_connect_timeout=0.5, health_check_interval=30)
    return RedisBackend(redis_client, memory) if redis_client is not None else memory


class RateLimiter:
    def __init__(self, settings, backend, auth: ApiKeyAuth):
        self.backend = backend
        self.auth = auth
        self.limits = {"api": settings.rate_limit_per_min, "llm": settings.llm_rate_limit_per_min}

    @property
    def shared(self) -> bool:
        return isinstance(self.backend, RedisBackend)

    def identity(self, request) -> str:
        key = request.headers.get("x-api-key")
        if self.auth.enabled and key and self.auth.verify(key):
            return "key:" + ApiKeyAuth.fingerprint(key)  # nosemgrep: directly-returned-format-string - rate-limit key, never an HTTP body
        client = getattr(request, "client", None)
        return "ip:" + (getattr(client, "host", None) or "unknown")

    async def check(self, request, scope: str) -> None:
        limit = self.limits[scope]
        if limit <= 0:
            return
        decision = await self.backend.hit(f"{scope}:{self.identity(request)}", limit, WINDOW_S)
        headers = {"X-RateLimit-Limit": str(decision.limit), "X-RateLimit-Remaining": str(decision.remaining),
                   "X-RateLimit-Reset": str(decision.reset_s)}
        state = request.scope.setdefault("state", {})
        current: Optional[Dict[str, str]] = state.get("ratelimit")
        if current is None or int(current["X-RateLimit-Remaining"]) >= decision.remaining:
            state["ratelimit"] = headers
        if not decision.allowed:
            what = "AI requests" if scope == "llm" else "requests"
            raise ApiError(429, "E_RATE_LIMITED",
                           f"Rate limit exceeded: {limit} {what} per minute. Retry in {decision.reset_s} s.",
                           headers={"Retry-After": str(decision.reset_s), **headers})

    async def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if close is not None:
            await close()
