import asyncio
import hmac

import pytest
from pydantic import SecretStr

from app.auth import ApiKeyAuth
from app.errors import ApiError
from app.ratelimit import MemoryBackend, RateLimiter, RedisBackend
from app.settings import Settings

KEY = "k" * 32
OTHER = "o" * 32


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------------------- auth
def test_open_mode_accepts_anything():
    auth = ApiKeyAuth([])
    assert not auth.enabled
    assert auth.verify(None) and auth.verify("whatever")


def test_keys_are_checked():
    auth = ApiKeyAuth([SecretStr(KEY), SecretStr(OTHER)])
    assert auth.enabled
    assert auth.verify(KEY) and auth.verify(OTHER)
    for bad in (None, "", KEY[:-1], KEY + "x", " " + KEY, "x" * 10_000):
        assert not auth.verify(bad)


def test_compare_is_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((len(a), len(b)))
        return real(a, b)

    monkeypatch.setattr("app.auth.hmac.compare_digest", spy)
    auth = ApiKeyAuth([SecretStr(KEY), SecretStr(OTHER)])
    auth.verify("short")
    assert calls == [(32, 32), (32, 32)]  # every key compared, fixed-length digests


def test_fingerprint_never_contains_the_key():
    fp = ApiKeyAuth.fingerprint(KEY)
    assert KEY not in fp and len(fp) == 16


# ------------------------------------------------------------------------------- backends
class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_fixed_window_counts_and_rolls_over():
    clock = Clock(999_980.0)  # 20 s into the window that starts at 999_960 (a multiple of 60)
    mem = MemoryBackend(clock=clock)
    decisions = [run(mem.hit("api:ip:1", 3, 60)) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert decisions[-1].reset_s == 40
    clock.t += 41  # next window
    d = run(mem.hit("api:ip:1", 3, 60))
    assert d.allowed and d.remaining == 2


def test_keys_are_isolated():
    mem = MemoryBackend(clock=Clock())
    for _ in range(3):
        run(mem.hit("api:key:a", 3, 60))
    assert not run(mem.hit("api:key:a", 3, 60)).allowed
    assert run(mem.hit("api:key:b", 3, 60)).allowed
    assert run(mem.hit("llm:key:a", 3, 60)).allowed


def test_memory_backend_is_bounded():
    clock = Clock()
    mem = MemoryBackend(clock=clock, max_keys=50)
    for i in range(200):
        run(mem.hit(f"api:ip:{i}", 5, 60))
        clock.t += 1
    assert len(mem) <= 60


def _fake_redis():
    fakeredis = pytest.importorskip("fakeredis")
    return fakeredis.FakeAsyncRedis()


def test_redis_backend_shares_counts_between_workers():
    async def scenario():
        client = _fake_redis()
        clock = Clock(999_980.0)
        worker_a = RedisBackend(client, MemoryBackend(clock=clock), clock=clock)
        worker_b = RedisBackend(client, MemoryBackend(clock=clock), clock=clock)
        results = []
        for i in range(4):
            backend = worker_a if i % 2 == 0 else worker_b
            results.append(await backend.hit("api:ip:9", 3, 60))
        clock.t += 60
        after = await worker_a.hit("api:ip:9", 3, 60)
        return results, after

    results, after = run(scenario())
    assert [d.allowed for d in results] == [True, True, True, False]
    assert after.allowed


def test_redis_failure_falls_back_to_the_in_memory_limiter():
    class Broken:
        def pipeline(self, *a, **k):
            raise ConnectionError("redis down")

    clock = Clock()
    backend = RedisBackend(Broken(), MemoryBackend(clock=clock), clock=clock)
    decisions = [run(backend.hit("api:ip:1", 2, 60)) for _ in range(3)]
    assert [d.allowed for d in decisions] == [True, True, False]


# ------------------------------------------------------------------------------- limiter
class Req:
    def __init__(self, ip="203.0.113.7", key=None):
        self.headers = {"x-api-key": key} if key else {}
        self.client = type("C", (), {"host": ip})()
        self.scope = {"state": {}}


def limiter(**kw):
    s = Settings(**kw)
    return RateLimiter(s, MemoryBackend(clock=Clock(999_960.0)), ApiKeyAuth(s.api_keys))  # window start


def test_limiter_raises_429_with_retry_after_and_rate_headers():
    lim = limiter(rate_limit_per_min=2)
    req = Req()
    run(lim.check(req, "api"))
    run(lim.check(req, "api"))
    with pytest.raises(ApiError) as exc:
        run(lim.check(req, "api"))
    err = exc.value
    assert (err.status, err.code) == (429, "E_RATE_LIMITED")
    assert err.headers["Retry-After"] == "60"
    assert err.headers["X-RateLimit-Limit"] == "2" and err.headers["X-RateLimit-Remaining"] == "0"
    assert req.scope["state"]["ratelimit"]["X-RateLimit-Remaining"] == "0"


def test_llm_budget_is_separate_and_stricter():
    lim = limiter(rate_limit_per_min=100, llm_rate_limit_per_min=1)
    req = Req()
    run(lim.check(req, "api"))
    run(lim.check(req, "llm"))
    with pytest.raises(ApiError):
        run(lim.check(req, "llm"))
    run(lim.check(req, "api"))  # general budget unaffected


def test_headers_report_the_tightest_scope():
    lim = limiter(rate_limit_per_min=100, llm_rate_limit_per_min=5)
    req = Req()
    run(lim.check(req, "api"))
    run(lim.check(req, "llm"))
    assert req.scope["state"]["ratelimit"]["X-RateLimit-Limit"] == "5"


def test_zero_disables_a_scope():
    lim = limiter(rate_limit_per_min=0)
    for _ in range(50):
        run(lim.check(Req(), "api"))


def test_identity_uses_the_api_key_only_when_auth_is_enabled():
    open_lim = limiter()
    assert open_lim.identity(Req(key="random-rotating-key")) == "ip:203.0.113.7"
    keyed = limiter(api_keys=KEY)
    ident = keyed.identity(Req(key=KEY))
    assert ident.startswith("key:") and KEY not in ident
    assert keyed.identity(Req(ip="198.51.100.1")) == "ip:198.51.100.1"


def test_clients_are_isolated_by_ip():
    lim = limiter(rate_limit_per_min=1)
    run(lim.check(Req(ip="10.0.0.1"), "api"))
    run(lim.check(Req(ip="10.0.0.2"), "api"))
    with pytest.raises(ApiError):
        run(lim.check(Req(ip="10.0.0.1"), "api"))
