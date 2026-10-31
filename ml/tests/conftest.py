"""six-gate-build scaffold: tests under tests/unit get the `unit` marker and tests under
tests/integration get `integration`, so `pytest -m unit` / `pytest -m integration` work
without decorating every test. Shared fixtures below."""
import random
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
ML_DIR = _HERE.parent
if str(ML_DIR) not in sys.path:
    sys.path.insert(0, str(ML_DIR))


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


STYLE_PLATFORMS = [("rslogix500", "rockwell_slc"), ("studio5000", "rockwell_logix"), ("tia", "siemens_tia"),
                   ("iec", "generic_iec"), ("printed", "rockwell_slc"), ("printed", "generic_iec"),
                   ("dark", "rockwell_logix"), ("dark", "siemens_tia")]


def compose_example(style_name: str, platform: str, seed: int, n_rungs: int = 6, want_end: bool = False):
    """A clean (unaugmented) composition for one style/platform."""
    from generator.compose import Composer
    from generator.sampler import ProgramSampler
    from generator.styles import sample_style

    for attempt in range(50):
        rng = random.Random(f"test:{style_name}:{platform}:{seed}:{attempt}")
        style = sample_style(style_name, rng, platform)
        prog = ProgramSampler(platform, rng, comment_rate=style.comment_rate).sample(n_rungs)
        comp = Composer(style, platform, rng, 736).compose(prog.text(), want_end)
        if comp is not None:
            return comp
    raise RuntimeError("could not compose an example")


@pytest.fixture(scope="session")
def compositions():
    """One clean composition per style/platform pair (plus END rungs for the Rockwell ones)."""
    return [compose_example(s, p, k, want_end=p.startswith("rockwell")) for k, (s, p) in enumerate(STYLE_PLATFORMS)]
