"""Photo / scan augmentations with exact box transforms.

Geometry: scale, mild perspective, rotation (<= 2 degrees) and padding are folded into one 3x3
homography in *pixel-edge* coordinates (x = 0 is the left edge of column 0). Box hulls (convex
hull of each element's ink, from the rasteriser) are mapped through it and the transformed AABB
is clipped to the image; a box keeping < 40 % of its area is dropped. OpenCV warps with pixel
*centres* at integer coordinates, so the matrix handed to cv2 is conjugated by a half-pixel shift.

Photometric: uneven lighting, brightness/contrast/gamma, colour cast, screen-photo moire, blur,
noise and JPEG, applied after the geometry.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

MIN_VISIBLE = 0.40
Box = Tuple[float, float, float, float]


@dataclass
class AugResult:
    image: Image.Image
    boxes: Dict[str, Optional[Box]]          # key -> transformed, clipped box (None = dropped)
    params: Dict[str, object] = field(default_factory=dict)
    jpeg_quality: Optional[int] = None
    size: Tuple[int, int] = (0, 0)
    matrix: Optional[np.ndarray] = None      # homography in pixel-edge coordinates
    prescale: float = 1.0


def _shift(dx: float, dy: float) -> np.ndarray:
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64)


def edge_to_cv(m_edge: np.ndarray) -> np.ndarray:
    """Matrix in pixel-edge coordinates -> the same mapping in OpenCV's pixel-centre coordinates."""
    return _shift(-0.5, -0.5) @ m_edge @ _shift(0.5, 0.5)


def apply_h(m: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    hom = np.hstack([pts, np.ones((len(pts), 1))]) @ m.T
    return hom[:, :2] / hom[:, 2:3]


def transform_box(m: np.ndarray, hull: np.ndarray, size: Tuple[int, int],
                  min_visible: float = MIN_VISIBLE) -> Optional[Box]:
    """AABB of the transformed hull, clipped to the image; None when < min_visible stays inside."""
    p = apply_h(m, hull)
    x0, y0 = p.min(axis=0)
    x1, y1 = p.max(axis=0)
    w, h = size
    area = max(1e-9, (x1 - x0) * (y1 - y0))
    cx0, cy0, cx1, cy1 = max(0.0, x0), max(0.0, y0), min(float(w), x1), min(float(h), y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return None
    if (cx1 - cx0) * (cy1 - cy0) / area < min_visible:
        return None
    return float(cx0), float(cy0), float(cx1), float(cy1)


def geometry(rng: random.Random, size: Tuple[int, int], level: str) -> Tuple[np.ndarray, Tuple[int, int], float, dict]:
    """Sample a homography (edge coords) and the output size. Returns (M, out_size, prescale, params)."""
    w, h = size
    if level == "light":
        s = rng.uniform(0.85, 1.15)
        rot = rng.uniform(-0.5, 0.5) if rng.random() < 0.3 else 0.0
        persp = 0.0
        pad = rng.uniform(0.0, 0.02) if rng.random() < 0.3 else 0.0
    else:
        s = rng.uniform(0.75, 1.3)
        rot = rng.uniform(-2.0, 2.0)
        persp = rng.uniform(0.004, 0.025)
        pad = rng.uniform(0.01, 0.05)
    sw, sh = max(8, int(round(w * s))), max(8, int(round(h * s)))
    px, py = int(round(pad * sw)), int(round(pad * sh))
    out = (sw + 2 * px, sh + 2 * py)
    sx, sy = sw / w, sh / h
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)
    dst = src * np.array([sx, sy]) + np.array([px, py])
    # rotation about the output centre
    c = np.array([out[0] / 2, out[1] / 2])
    a = math.radians(rot)
    rmat = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    dst = (dst - c) @ rmat.T + c
    # perspective: jitter corners
    if persp > 0:
        jitter = np.array([[rng.uniform(-1, 1) * persp * out[0], rng.uniform(-1, 1) * persp * out[1]] for _ in range(4)])
        dst = dst + jitter
    m = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32)).astype(np.float64)
    params = {"scale": round(s, 4), "rotation_deg": round(rot, 3), "perspective": round(persp, 4), "pad": round(pad, 4)}
    return m, out, s, params


def warp(img: np.ndarray, m_edge: np.ndarray, out: Tuple[int, int], prescale: float, border: Tuple[int, int, int]) -> np.ndarray:
    """Warp with the edge-coordinate homography. Strong downscales go through INTER_AREA first."""
    h, w = img.shape[:2]
    if prescale < 0.92:
        sw, sh = max(8, int(round(w * prescale))), max(8, int(round(h * prescale)))
        img = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        pre = np.diag([sw / w, sh / h, 1.0])
        m_edge = m_edge @ np.linalg.inv(pre)
    return cv2.warpPerspective(img, edge_to_cv(m_edge), out, flags=cv2.INTER_LINEAR,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=tuple(int(v) for v in border))


# ------------------------------------------------------------------------------------- photometric


def _lighting(a: np.ndarray, rng: random.Random) -> Tuple[np.ndarray, dict]:
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    if rng.random() < 0.5:
        ang = rng.uniform(0, 2 * math.pi)
        g = (xx / w - 0.5) * math.cos(ang) + (yy / h - 0.5) * math.sin(ang)
        k = rng.uniform(0.08, 0.3)
        field_ = 1.0 + k * g
        kind = "gradient"
    else:
        cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h
        r2 = ((xx - cx) / w) ** 2 + ((yy - cy) / h) ** 2
        k = rng.uniform(0.15, 0.5)
        field_ = 1.0 - k * r2
        kind = "vignette"
    return a * field_[..., None], {"lighting": kind, "lighting_k": round(k, 3)}


def _moire(a: np.ndarray, rng: random.Random) -> Tuple[np.ndarray, dict]:
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    f1 = rng.uniform(0.25, 0.45)
    df = rng.uniform(0.004, 0.02)
    t1, t2 = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
    g1 = np.sin(2 * math.pi * f1 * (xx * math.cos(t1) + yy * math.sin(t1)))
    g2 = np.sin(2 * math.pi * (f1 + df) * (xx * math.cos(t2) + yy * math.sin(t2)))
    amp = rng.uniform(0.04, 0.12)
    pattern = 1.0 + amp * g1 * g2
    out = a * pattern[..., None]
    if rng.random() < 0.5:  # LCD sub-pixel stripes
        phase = np.stack([np.sin(2 * math.pi * (xx / 3.0 + k / 3.0)) for k in range(3)], axis=-1)
        out = out * (1.0 + rng.uniform(0.02, 0.06) * phase)
    return out, {"moire_amp": round(amp, 3), "moire_df": round(df, 4)}


def photometric(img: np.ndarray, rng: random.Random, level: str) -> Tuple[np.ndarray, dict, Optional[int]]:
    a = img.astype(np.float32)
    params: dict = {}
    heavy = level == "heavy"
    if heavy and rng.random() < 0.6:
        a, p = _lighting(a, rng)
        params.update(p)
    if heavy and rng.random() < 0.3:
        a, p = _moire(a, rng)
        params.update(p)
    if rng.random() < (0.8 if heavy else 0.5):
        c = rng.uniform(0.7, 1.2) if heavy else rng.uniform(0.85, 1.1)
        b = rng.uniform(-30, 25) if heavy else rng.uniform(-12, 12)
        a = (a - 128.0) * c + 128.0 + b
        params.update({"contrast": round(c, 3), "brightness": round(b, 2)})
    if rng.random() < (0.5 if heavy else 0.25):
        gamma = rng.uniform(0.7, 1.4) if heavy else rng.uniform(0.85, 1.15)
        a = 255.0 * np.clip(a / 255.0, 0, 1) ** gamma
        params["gamma"] = round(gamma, 3)
    if heavy and rng.random() < 0.4:
        cast = np.array([rng.uniform(0.9, 1.08) for _ in range(3)], dtype=np.float32)
        a = a * cast
        params["cast"] = [round(float(v), 3) for v in cast]
    a = np.clip(a, 0, 255)
    if rng.random() < (0.6 if heavy else 0.3):
        sigma = rng.uniform(0.4, 1.3) if heavy else rng.uniform(0.3, 0.7)
        a = cv2.GaussianBlur(a, (0, 0), sigma)
        params["blur_sigma"] = round(sigma, 3)
    if rng.random() < (0.6 if heavy else 0.3):
        sigma = rng.uniform(2.0, 9.0) if heavy else rng.uniform(1.0, 3.5)
        nrng = np.random.default_rng(rng.getrandbits(32))
        a = a + nrng.normal(0.0, sigma, a.shape).astype(np.float32)
        params["noise_sigma"] = round(sigma, 3)
    out = np.clip(a + 0.5, 0, 255).astype(np.uint8)
    quality = None
    if rng.random() < (0.7 if heavy else 0.45):
        quality = rng.randint(35, 80) if heavy else rng.randint(60, 95)
        ok, enc = cv2.imencode(".jpg", cv2.cvtColor(out, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok:
            out = cv2.cvtColor(cv2.imdecode(enc, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
            params["jpeg_quality"] = quality
        else:  # pragma: no cover
            quality = None
    return out, params, quality


def augment(image: Image.Image, hulls: Dict[str, np.ndarray], rng: random.Random, level: str,
            bg: Tuple[int, int, int]) -> AugResult:
    """Apply a 'light' or 'heavy' augmentation. ``hulls`` maps element keys to ink hulls."""
    if level not in ("light", "heavy"):
        raise ValueError(level)
    src = np.asarray(image.convert("RGB"))
    h, w = src.shape[:2]
    m, out, prescale, gparams = geometry(rng, (w, h), level)
    border = bg
    if level == "heavy" and rng.random() < 0.35:   # screen bezel / desk around a photographed screen
        border = rng.choice([(20, 20, 20), (45, 45, 50), (120, 110, 100), (200, 200, 200)])
    warped = warp(src, m, out, prescale, border)
    boxes = {k: transform_box(m, hull, out) for k, hull in hulls.items()}
    final, pparams, quality = photometric(warped, rng, level)
    params = {"level": level, **gparams, **pparams, "border": list(border)}
    return AugResult(Image.fromarray(final), boxes, params, quality, out, m, prescale)
