"""six-gate-build, gate 6: simulate thousands of users walking the build's real journey.

Ramps users up in steps until something breaks, times every whole journey (FLOW rows,
so you see whether users can still *finish* what they came to do, not just whether
endpoints answer), and refuses to send a single request to a host that is not loopback
or explicitly allow-listed (every request, redirect and absolute URL is checked).

Copy this file AND target_guard.py into the project (e.g. PROJECT/loadtest/), edit
run_journey(), start the build locally, then:

    locust -f loadtest/locustfile.py --headless --host http://127.0.0.1:8000 \
        --csv .six-gate/load --csv-full-history --html .six-gate/load.html
    python <skill>/scripts/analyze_load.py .six-gate/load_stats_history.csv --out .six-gate/load.md

Tuning via environment variables [defaults]:
    SIX_GATE_STEP_USERS   [100]   users added per step
    SIX_GATE_STEP_SECONDS [20]    seconds per step; keep >= 15 so the metrics settle
    SIX_GATE_MAX_USERS    [1000]  the last step
    SIX_GATE_SPAWN_RATE   [50]    users started per second
    SIX_GATE_ABORT_FAIL   [0.5]   stop at the end of a step once this share of requests fails
    SIX_GATE_PATHS        [/]     comma-separated GET paths for the default journey
    SIX_GATE_SHAPE        [step]  'off' to use plain -u / -r / -t instead of the ramp
    SIX_GATE_ALLOWED_HOSTS        staging hosts you own, exact names, comma-separated
"""
from __future__ import annotations

import logging
import math
import os
import sys
from urllib.parse import urlsplit

from locust import HttpUser, LoadTestShape, between, events, task
from locust.clients import LocustHttpAdapter
from requests.exceptions import RequestException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from target_guard import TargetNotAllowed, check_target  # noqa: E402


def _env(name, default, cast):
    raw = os.environ.get(name, default)
    try:
        return cast(raw)
    except ValueError:
        logging.warning("six-gate: ignoring %s=%r, using %s", name, raw, default)
        return cast(default)


STEP_USERS = max(1, _env("SIX_GATE_STEP_USERS", "100", int))
STEP_SECONDS = max(5, _env("SIX_GATE_STEP_SECONDS", "20", int))
MAX_USERS = max(1, _env("SIX_GATE_MAX_USERS", "1000", int))
SPAWN_RATE = max(0.1, _env("SIX_GATE_SPAWN_RATE", "50", float))
ABORT_FAIL = min(1.0, max(0.0, _env("SIX_GATE_ABORT_FAIL", "0.5", float)))
PATHS = [p.strip() for p in os.environ.get("SIX_GATE_PATHS", "/").split(",") if p.strip()]


class TargetBlocked(RequestException):
    """Raised instead of sending a request to a host the guard refuses (recorded as a failure)."""


class FlowStepFailed(Exception):
    """A journey step returned something other than what a real user needs."""


class GuardedAdapter(LocustHttpAdapter):
    """Re-checks every outgoing request, including redirects and absolute URLs, before it leaves."""

    def send(self, request, *args, **kwargs):
        parts = urlsplit(request.url)
        try:
            check_target(f"{parts.scheme}://{parts.netloc}")
        except TargetNotAllowed as exc:
            raise TargetBlocked(str(exc)) from None
        return super().send(request, *args, **kwargs)


@events.test_start.add_listener
def _refuse_foreign_targets(environment, **_kwargs):
    try:
        check_target(environment.host or "")
    except TargetNotAllowed as exc:
        logging.error("six-gate: %s", exc)
        environment.process_exit_code = 2
        if environment.runner is not None:
            environment.runner.quit()


class JourneyUser(HttpUser):
    """One simulated person. Edit run_journey() to walk the build's real flow."""

    wait_time = between(1, 3)  # think time between journeys

    def on_start(self):
        pool = self.client.get_adapter("http://").poolmanager  # keep Locust's connection pool
        for prefix in ("http://", "https://"):
            self.client.mount(prefix, GuardedAdapter(pool_manager=pool))

    def step(self, method, path, name=None, expect=(200,), **kwargs):
        """One journey step. Paths are relative to --host; any status outside `expect` fails
        both this request and the whole journey. Group URLs with ids via name, e.g. name="/items/[id]"."""
        if not path.startswith("/"):
            raise FlowStepFailed(f"use a path relative to --host, got {path!r}")
        with self.client.request(method, path, name=name or path, catch_response=True, **kwargs) as resp:
            ok = resp.status_code in expect
            if not ok:
                # status 0 means no response at all: say why (guard refusal, connection refused, timeout)
                why = f"no response: {resp.error!r}" if resp.status_code == 0 and getattr(resp, "error", None) else f"HTTP {resp.status_code}"
                resp.failure(f"{why}, expected {'/'.join(map(str, expect))}")
        if not ok:
            raise FlowStepFailed(f"{method} {name or path} -> {why}")
        return resp

    @task
    def journey(self):
        with self.environment.events.request.measure("FLOW", "journey"):
            self.run_journey()

    def run_journey(self):
        """LogicLens user: open the app (health + meta), analyse pasted text, recognise a screenshot.

        Image recognition is the expensive step (decode, YOLO, OCR). Set LOGICLENS_LOAD_IMAGE to a
        PNG/JPEG/WEBP to include it (the repo sample is the default); LOGICLENS_LOAD_IMAGE=none skips it.
        """
        self.step("GET", "/health")
        self.step("GET", "/api/meta")
        self.step("POST", "/api/analyze/text", json={"text": LOAD_PROGRAM, "platform": "rockwell_logix"})
        if LOAD_IMAGE is not None:
            self.step("POST", "/api/analyze/parse", name="/api/analyze/parse [image]",
                      files={"file": ("plc.webp", LOAD_IMAGE, "image/webp")}, timeout=120)


LOAD_PROGRAM = (
    "// Motor M-101\n[XIC(Start_PB),XIC(Motor_Run)]XIC(Stop_PB)XIC(OL_Relay)OTE(Motor_Run);\n"
    "XIC(Motor_Run)TON(Run_Timer,5000,0);\nXIC(Run_Timer.DN)OTE(Run_Lamp);"
)
_img = os.environ.get("LOGICLENS_LOAD_IMAGE", os.path.join(os.path.dirname(__file__), "..", "..", "samples", "ladder_logic_program_PLC1.webp"))
LOAD_IMAGE = None if _img.lower() == "none" else open(_img, "rb").read()


if os.environ.get("SIX_GATE_SHAPE", "step").lower() != "off":

    class StepRamp(LoadTestShape):
        """+STEP_USERS every STEP_SECONDS up to MAX_USERS. Stops after the last step, or at the end
        of a step that is clearly broken (>= ABORT_FAIL failing), so every recorded step is complete."""

        def tick(self):
            run_time = self.get_run_time()
            step = int(run_time // STEP_SECONDS)
            if step >= math.ceil(MAX_USERS / STEP_USERS):
                return None
            if step != getattr(self, "_step", 0):
                self._step = step
                if self._broken():
                    return None
            return min(MAX_USERS, (step + 1) * STEP_USERS), SPAWN_RATE

        def _broken(self) -> bool:
            if self.runner is None:
                return False
            total = self.runner.stats.total
            rps = total.current_rps or 0
            if rps > 0 and (total.current_fail_per_sec or 0) / rps >= ABORT_FAIL:
                logging.warning("six-gate: %.0f%% of recent requests failing: stopping the ramp here",
                                100 * total.current_fail_per_sec / rps)
                return True
            return False
