"""six-gate-build scaffold: tests under tests/unit get the `unit` marker and tests under
tests/integration get `integration`, so `pytest -m unit` / `pytest -m integration` work
without decorating every test. Shared fixtures live below."""
import os
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = getattr(item, "path", None) or item.fspath  # item.path on pytest >= 7
        try:
            parts = Path(str(path)).resolve().relative_to(_HERE).parts
        except ValueError:
            continue
        if parts and parts[0] == "unit":
            item.add_marker(pytest.mark.unit)
        elif parts and parts[0] == "integration":
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """A developer's shell must never leak real keys or config into the tests."""
    for name in list(os.environ):
        if name.startswith("LOGICLENS_") or name in ("ANTHROPIC_API_KEY", "REDIS_URL"):
            monkeypatch.delenv(name, raising=False)
    yield
