"""The exported detector (ml/models/*.onnx) through the backend's exact pipeline.

Skipped until a model exists. Images are fresh test-split samples from another seed (programs
can never coincide with training programs, see dataset.split_of). Thresholds sit well below the
pilot's measured numbers (models/metrics.json): they catch a broken export or a regression, not
small fluctuations.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ML_DIR = Path(__file__).resolve().parents[2]
MODELS = sorted((ML_DIR / "models").glob("*.onnx"))
sys.path.insert(0, str(ML_DIR / "train"))

pytestmark = pytest.mark.skipif(not MODELS, reason="no exported model in ml/models")


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


@pytest.fixture(scope="module")
def detector():
    from onnx_infer import OnnxDetector
    assert len(MODELS) == 1, f"keep exactly one model in ml/models (the backend test runs each): {MODELS}"
    return OnnxDetector(MODELS[0], threads=2, conf=0.25)


@pytest.fixture(scope="module")
def results(detector):
    from generator.dataset import make_sample
    out = []
    for i in range(16):
        s = make_sample(99, "test", i, aug="none")
        out.append((s, detector(s.image)))
    return out


def test_model_contract(detector):
    from generator.contract import NC
    assert detector.nc == NC and detector.hw[0] == detector.hw[1] and detector.hw[0] % 32 == 0
    assert detector.impl in ("backend", "local")


def test_symbols_are_found_with_the_right_class(results):
    tp_cls = tp_loc = n_gt = n_det = 0
    for s, dets in results:
        gts = [lab for lab in s.labels if lab[0] < 38]
        sym_dets = [d for d in dets if d[0] < 38]
        n_gt += len(gts)
        n_det += len(sym_dets)
        used = set()
        for cid, *box in gts:
            best, bj = 0.0, None
            for j, (dc, p, db) in enumerate(sym_dets):
                if j not in used and (v := _iou(box, db)) > best:
                    best, bj = v, j
            if bj is not None and best >= 0.5:
                used.add(bj)
                tp_loc += 1
                tp_cls += sym_dets[bj][0] == cid
    recall_cls, recall_loc, precision_loc = tp_cls / n_gt, tp_loc / n_gt, tp_loc / max(1, n_det)
    # pilot measured 1.00 / 0.94 / 0.95 on these images
    assert recall_loc >= 0.90, recall_loc
    assert recall_cls >= 0.80, recall_cls
    assert precision_loc >= 0.85, precision_loc


def _structure_hit_rate(results, ids):
    hits = total = 0
    for s, dets in results:
        for cid, *box in s.labels:
            if cid in ids:
                total += 1
                hits += any(dc == cid and _iou(box, db) >= 0.5 for dc, p, db in dets)
    return hits / total


def test_branch_connectors_are_found(results):
    assert _structure_hit_rate(results, (40, 41)) >= 0.90  # pilot: 66/66


def test_power_rails_are_at_least_sometimes_found(results):
    """Known weakness (model_card.md): a 5-7 px wide, full-height box rarely contains a stride-32
    anchor centre, so rails are found with loose boxes or missed (pilot: 12/32 at IoU 0.5). The
    assembler only uses rails to bound OCR crops. This guards against a total loss only."""
    assert _structure_hit_rate(results, (42, 43)) >= 0.15


def test_boxes_are_finite_and_inside_the_image(results):
    for s, dets in results:
        w, h = s.image.size
        for c, p, b in dets:
            assert np.isfinite(b).all() and 0 <= b[0] < b[2] <= w and 0 <= b[1] < b[3] <= h and 0 < p <= 1
