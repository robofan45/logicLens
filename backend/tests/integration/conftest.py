import json

import pytest
from fastapi.testclient import TestClient

from app.engines.ocr import FakeOcr
from app.main import create_app
from app.settings import Settings
from tests.helpers import REPO


@pytest.fixture(scope="session")
def program_schema():
    path = REPO / "contract" / "program.schema.json"
    if not path.exists():
        pytest.skip("contract/program.schema.json not available")
    return json.loads(path.read_text())


@pytest.fixture
def make_client():
    """make_client(settings_kw..., llm=..., detector_factory=..., ocr=...) -> TestClient (lifespan running)."""
    clients = []

    def _make(*, llm=None, detector_factory=None, ocr=None, redis_client=None, **settings_kw):
        app = create_app(Settings(**settings_kw), llm_client=llm, detector_factory=detector_factory,
                         ocr=ocr if ocr is not None else FakeOcr([]), redis_client=redis_client)
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
