"""The real RSLogix 500 screenshot through the assembler with the real tesseract binary.

The YOLO model is still being trained, so the detections here are hand-labelled boxes of the kind
the model produces (tight around each symbol graphic, contract section 6). Box jitter of +/-3 px
simulates detector imprecision; the expected output is the ground truth, exactly.
"""
import random
import shutil

import pytest
from PIL import Image

from app.engines.assembler import assemble
from app.engines.base import CLASSES, Detection
from app.engines.ocr import TesseractOcr
from app.program import finalize_rungs
from tests.helpers import SAMPLE_IMAGE, SAMPLE_TRUTH

pytestmark = pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")

ID = {c.name: c.id for c in CLASSES}
HAND_LABELS = [
    ("Power_Rail_Left", (82, 16, 89, 469)), ("Power_Rail_Right", (830, 16, 837, 469)),
    ("NO_Contact", (162, 73, 186, 91)), ("NO_Contact", (263, 73, 286, 91)), ("Output_Coil", (770, 73, 799, 90)),
    ("NO_Contact", (211, 180, 235, 198)), ("Output_Coil", (770, 180, 799, 197)),
    ("NO_Contact", (211, 273, 235, 291)),
    ("Branch_Start", (160, 186, 167, 285)), ("Branch_End", (284, 186, 291, 285)),
    ("NC_Contact", (162, 365, 188, 383)), ("NC_Contact", (259, 365, 285, 383)),
    ("NC_Contact", (357, 365, 383, 383)), ("Output_Coil", (770, 366, 799, 383)),
]


def hand_detections(jitter_seed=None):
    rng = random.Random(jitter_seed)
    dets = []
    for name, box in HAND_LABELS:
        if jitter_seed is not None:
            box = tuple(v + rng.uniform(-3, 3) for v in box)
        dets.append(Detection(ID[name], 0.9, tuple(float(v) for v in box)))
    return dets


@pytest.fixture(scope="module")
def sample():
    return Image.open(SAMPLE_IMAGE).convert("RGB")


@pytest.mark.parametrize("seed", [None, 1, 2, 3])
def test_sample_screenshot_assembles_to_the_ground_truth(sample, seed):
    result = assemble(sample, hand_detections(seed), TesseractOcr())
    warnings = list(result.warnings)
    rungs = finalize_rungs(result.rungs, warnings)
    assert [r.text for r in rungs] == SAMPLE_TRUTH
    assert warnings == []
    assert all(e.bbox is not None for r in rungs for e in r.elements)


def test_tesseract_is_called_without_temporary_files(sample, monkeypatch, tmp_path):
    """Zero retention: OCR must not write crops to disk (pytesseract would, via tempfile)."""
    import tempfile

    def no_temp(*args, **kwargs):  # pragma: no cover - failing path
        raise AssertionError("OCR tried to create a temporary file")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", no_temp)
    monkeypatch.setattr(tempfile, "mkstemp", no_temp)
    monkeypatch.setattr(tempfile, "mkdtemp", no_temp)
    result = assemble(sample, hand_detections(), TesseractOcr())
    assert len(result.rungs) == 3
