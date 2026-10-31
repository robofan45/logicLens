import threading
import time

import pytest

from app.errors import ApiError
from app.gate import Gate


def test_slots_up_to_the_limit_run_concurrently():
    gate = Gate("cpu", limit=2, max_waiting=0, timeout_s=0.2)
    with gate.slot():
        with gate.slot():
            assert gate.in_use == 2


def test_queue_timeout_is_503_busy_with_retry_after():
    gate = Gate("cpu", limit=1, max_waiting=4, timeout_s=0.05)
    with gate.slot():
        started = time.monotonic()
        with pytest.raises(ApiError) as exc:
            with gate.slot():
                pass  # pragma: no cover
        assert time.monotonic() - started >= 0.05
    assert (exc.value.status, exc.value.code) == (503, "E_BUSY")
    assert "Retry-After" in exc.value.headers


def test_full_queue_rejects_immediately():
    gate = Gate("cpu", limit=1, max_waiting=0, timeout_s=5)
    with gate.slot():
        started = time.monotonic()
        with pytest.raises(ApiError):
            with gate.slot():
                pass  # pragma: no cover
        assert time.monotonic() - started < 1


def test_waiter_gets_the_slot_when_it_is_released():
    gate = Gate("cpu", limit=1, max_waiting=1, timeout_s=2)
    order = []
    release = threading.Event()

    def holder():
        with gate.slot():
            order.append("held")
            release.wait(1)

    t = threading.Thread(target=holder)
    t.start()
    while not order:
        time.sleep(0.001)
    threading.Timer(0.05, release.set).start()
    with gate.slot():
        order.append("waiter")
    t.join()
    assert order == ["held", "waiter"]
    assert gate.in_use == 0 and gate.waiting == 0


def test_slot_is_released_when_the_body_raises():
    gate = Gate("cpu", limit=1, max_waiting=0, timeout_s=0.01)
    with pytest.raises(RuntimeError):
        with gate.slot():
            raise RuntimeError("boom")
    with gate.slot():
        pass
