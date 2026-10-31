"""Bounded concurrency with a short queue, for CPU-heavy and LLM work inside one worker process.

The gate is used from worker threads (endpoints hand CPU work to the thread pool, so the event
loop never blocks). When all slots are busy a caller waits at most ``timeout_s``; when
``max_waiting`` callers are already waiting it is turned away at once. Either way the client gets
503 E_BUSY with Retry-After instead of an unbounded queue that eats memory.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from .errors import ApiError


class Gate:
    def __init__(self, name: str, limit: int, max_waiting: int, timeout_s: float, retry_after_s: int = 5):
        self.name = name
        self.limit = limit
        self.max_waiting = max_waiting
        self.timeout_s = timeout_s
        self.retry_after_s = retry_after_s
        self._sem = threading.BoundedSemaphore(limit)
        self._lock = threading.Lock()
        self._waiting = 0
        self._in_use = 0

    @property
    def waiting(self) -> int:
        return self._waiting

    @property
    def in_use(self) -> int:
        return self._in_use

    def _busy(self, why: str) -> ApiError:
        return ApiError(503, "E_BUSY", f"The server is busy ({self.name} {why}); retry shortly.",
                        headers={"Retry-After": str(self.retry_after_s)})

    @contextmanager
    def slot(self) -> Iterator[None]:
        if not self._sem.acquire(blocking=False):
            with self._lock:
                if self._waiting >= self.max_waiting:
                    raise self._busy("queue full")
                self._waiting += 1
            try:
                acquired = self._sem.acquire(timeout=self.timeout_s)
            finally:
                with self._lock:
                    self._waiting -= 1
            if not acquired:
                raise self._busy("queue timeout")
        with self._lock:
            self._in_use += 1
        try:
            yield
        finally:
            with self._lock:
                self._in_use -= 1
            self._sem.release()


class Gates:
    """The two gates every worker owns: CPU inference and outbound LLM calls."""

    def __init__(self, cpu: Gate, llm: Gate):
        self.cpu = cpu
        self.llm = llm

    @classmethod
    def from_settings(cls, settings) -> "Gates":
        return cls(
            Gate("inference", settings.inference_concurrency, settings.inference_queue, settings.queue_timeout_s),
            Gate("llm", settings.llm_concurrency, settings.llm_queue, settings.queue_timeout_s),
        )
