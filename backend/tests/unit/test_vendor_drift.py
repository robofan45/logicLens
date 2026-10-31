"""The backend vendors the contract's parser and class list so the Docker build context
(backend/ only) is self-contained. These tests fail the moment either copy drifts."""
import hashlib
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
CONTRACT = BACKEND.parent / "contract"
VENDOR = BACKEND / "app" / "vendor"

PAIRS = [
    (CONTRACT / "python" / "logiclens_ladder.py", VENDOR / "logiclens_ladder.py"),
    (CONTRACT / "classes.json", VENDOR / "classes.json"),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("source,copy", PAIRS, ids=[p[1].name for p in PAIRS])
def test_vendored_copy_is_byte_identical_to_contract(source, copy):
    if not source.exists():
        pytest.skip("contract/ is not available (for example inside the Docker build context)")
    assert copy.exists(), f"missing vendored copy {copy}"
    assert _sha256(copy) == _sha256(source), (
        f"{copy} drifted from {source}; re-copy it byte-for-byte (cp {source} {copy})"
    )


def test_vendored_parser_is_importable_and_parses_the_sample_ground_truth():
    from app.vendor.logiclens_ladder import parse_program, print_program

    text = (
        "XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);\n"
        "[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);\n"
        "XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);"
    )
    res = parse_program(text)
    assert res.ok
    assert print_program(res.rungs) == text


def test_vendored_classes_have_44_entries_with_contiguous_ids():
    import json

    data = json.loads((VENDOR / "classes.json").read_text())
    assert data["nc"] == 44
    assert [c["id"] for c in data["classes"]] == list(range(44))
