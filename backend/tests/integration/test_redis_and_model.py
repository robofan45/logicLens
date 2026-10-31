"""Wiring that needs real external pieces: a Redis server shared by two "workers", and the trained
YOLO model on the real sample screenshot (skipped until ml/ publishes ml/models/*.onnx)."""
import shutil
import socket
import subprocess
import time

import jsonschema
import pytest

from app.engines.ocr import TesseractOcr
from app.main import create_app
from app.settings import Settings
from fastapi.testclient import TestClient
from tests.helpers import REPO, SAMPLE_IMAGE, SAMPLE_TRUTH

PROGRAM = "XIC(A)OTE(B);"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    binary = shutil.which("redis-server")
    if binary is None:
        pytest.skip("redis-server not installed")
    port = _free_port()
    proc = subprocess.Popen([binary, "--port", str(port), "--bind", "127.0.0.1", "--save", "", "--appendonly", "no"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    else:  # pragma: no cover - environment problem
        proc.kill()
        pytest.skip("redis-server did not start")
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait(5)


def test_two_workers_share_one_budget_through_redis(redis_url):
    settings = Settings(redis_url=redis_url, rate_limit_per_min=3)
    with TestClient(create_app(settings)) as worker_a, TestClient(create_app(settings)) as worker_b:
        statuses = []
        for i in range(4):
            client = worker_a if i % 2 == 0 else worker_b
            statuses.append(client.post("/api/analyze/text", json={"text": PROGRAM},
                                        headers={"X-Forwarded-For": "ignored"}).status_code)
        assert statuses == [200, 200, 200, 429]
        meta = worker_a.get("/api/meta")
        assert meta.status_code == 429  # same client, same shared budget


def test_meta_reports_a_shared_limiter(redis_url):
    with TestClient(create_app(Settings(redis_url=redis_url, rate_limit_per_min=100))) as client:
        assert client.get("/api/meta").json()["limits"]["rate_limit_shared"] is True


def test_redis_outage_degrades_to_per_process_limits():
    dead = f"redis://127.0.0.1:{_free_port()}/0"
    with TestClient(create_app(Settings(redis_url=dead, rate_limit_per_min=2))) as client:
        statuses = [client.post("/api/analyze/text", json={"text": PROGRAM}).status_code for _ in range(3)]
    assert statuses == [200, 200, 429]


# --------------------------------------------------------------------------- trained model, real sample
MODELS = sorted((REPO / "ml" / "models").glob("*.onnx"))


@pytest.mark.skipif(not MODELS, reason="no trained YOLO model yet (ml/models/*.onnx)")
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
@pytest.mark.parametrize("model", MODELS, ids=[m.name for m in MODELS])
def test_real_sample_through_the_trained_yolo_model(model, program_schema):
    app = create_app(Settings(engine="yolo", yolo_onnx=model), ocr=TesseractOcr())
    with TestClient(app) as client:
        resp = client.post("/api/analyze/parse", files={"file": ("PLC1.webp", SAMPLE_IMAGE.read_bytes(), "image/webp")})
    assert resp.status_code == 200, resp.text
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert [r["text"] for r in program["rungs"]] == SAMPLE_TRUTH, program["warnings"]
