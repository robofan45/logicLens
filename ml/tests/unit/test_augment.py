"""Augmentation: boxes follow the pixels through the homography; clipping and dropping rules."""
import random

import cv2
import numpy as np
import pytest
from PIL import Image

from generator.augment import MIN_VISIBLE, apply_h, augment, edge_to_cv, geometry, transform_box, warp
from generator.raster import rasterize


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def test_identity_keeps_boxes():
    hull = np.array([[10, 20], [40, 20], [40, 30], [10, 30]], dtype=np.float32)
    assert transform_box(np.eye(3), hull, (100, 100)) == (10.0, 20.0, 40.0, 30.0)


def test_edge_to_cv_matches_opencv_resize_convention():
    # a 2x upscale in edge coordinates must equal cv2.resize's half-pixel mapping
    m = np.diag([2.0, 2.0, 1.0])
    pts_center = np.array([[0.0, 0.0], [3.0, 5.0]])
    mapped = apply_h(edge_to_cv(m), pts_center)
    assert np.allclose(mapped, pts_center * 2 + 0.5)


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("level", ["light", "heavy"])
def test_warped_ink_lies_inside_the_transformed_box(seed, level):
    rng = random.Random(seed)
    w, h = rng.randint(300, 900), rng.randint(200, 700)
    img = np.full((h, w, 3), 255, np.uint8)
    x0, y0 = rng.randint(20, w - 80), rng.randint(20, h - 60)
    x1, y1 = x0 + rng.randint(4, 60), y0 + rng.randint(4, 40)
    img[y0:y1, x0:x1] = 0
    hull = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    m, out, prescale, _ = geometry(rng, (w, h), level)
    warped = warp(img, m, out, prescale, (255, 255, 255))
    ink = _bbox(warped.min(axis=2) < 128)          # >= half coverage
    faint = _bbox(warped.min(axis=2) < 250)        # any visible coverage
    box = transform_box(m, hull, out, min_visible=0.0)
    assert box is not None
    # half-covered pixels are inside the box; the box is no more than ~1 px looser than the faint ink
    assert ink[0] >= box[0] - 0.5 and ink[1] >= box[1] - 0.5 and ink[2] <= box[2] + 0.5 and ink[3] <= box[3] + 0.5
    assert box[0] >= faint[0] - 1.0 and box[1] >= faint[1] - 1.0 and box[2] <= faint[2] + 1.0 and box[3] <= faint[3] + 1.0


def test_partially_outside_boxes_are_clipped_or_dropped():
    m = np.eye(3)
    half_out = np.array([[-10, 0], [10, 0], [10, 10], [-10, 10]], dtype=np.float32)
    assert transform_box(m, half_out, (100, 100)) == (0.0, 0.0, 10.0, 10.0)        # 50 % visible: kept
    mostly_out = np.array([[-70, 0], [30, 0], [30, 10], [-70, 10]], dtype=np.float32)
    assert transform_box(m, mostly_out, (100, 100)) is None                     # 30 % visible: dropped
    outside = np.array([[200, 0], [230, 0], [230, 10], [200, 10]], dtype=np.float32)
    assert transform_box(m, outside, (100, 100)) is None
    assert MIN_VISIBLE == 0.40


def test_augment_moves_every_symbol_box_with_its_pixels(compositions):
    """Warp each symbol drawn alone with the sample's own homography: its ink stays in its box."""
    for k, comp in enumerate(compositions[:5]):
        rng = random.Random(f"aug:{k}")
        res = augment(comp.image, comp.hulls, rng, "heavy", comp.style.bg)
        assert res.image.size == res.size
        w, h = comp.size
        for ins in comp.instructions[:8]:
            box = res.boxes[ins["key"]]
            if box is None:
                continue
            assert 0 <= box[0] < box[2] <= res.size[0] and 0 <= box[1] < box[3] <= res.size[1]
            el = next(e for e in comp.elements if e.key == ins["key"])
            alone, _ = rasterize(w, h, comp.style.ss, (255, 255, 255), [el])
            a = np.asarray(alone).copy()
            mask = (np.abs(a.astype(int) - 255).max(axis=2) > 0).astype(np.uint8) * 255
            mask3 = np.repeat(mask[..., None], 3, axis=2)
            warped = warp(mask3, res.matrix, res.size, res.prescale, (0, 0, 0))[..., 0]
            ink = _bbox(warped >= 128) if (warped >= 128).any() else None
            if ink is None:
                continue
            assert ink[0] >= box[0] - 1 and ink[1] >= box[1] - 1 and ink[2] <= box[2] + 1 and ink[3] <= box[3] + 1, \
                (comp.style.name, ins["mnemonic"], ink, box)


def test_photometric_output_is_valid_and_deterministic(compositions):
    comp = compositions[0]
    a = augment(comp.image, comp.hulls, random.Random(5), "heavy", comp.style.bg)
    b = augment(comp.image, comp.hulls, random.Random(5), "heavy", comp.style.bg)
    assert np.array_equal(np.asarray(a.image), np.asarray(b.image))
    assert a.boxes == b.boxes and a.params == b.params
    with pytest.raises(ValueError):
        augment(comp.image, comp.hulls, random.Random(5), "extreme", comp.style.bg)
