"""Rasteriser: draws primitive lists at a supersampling factor and measures each element's ink.

Every element is drawn twice from the same primitives: in colour onto the canvas and in white
onto a private mask patch aligned to the supersampling grid. ``Image.reduce`` turns both into
final pixels by block averaging, so the reduced mask is exactly that element's coverage in the
final image. Label boxes are the bounding box of that coverage: tight by construction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from .styles import FontSpec

RGB = Tuple[int, int, int]
Box = Tuple[float, float, float, float]


def _r(v: float) -> int:
    """Round half up (Python's round() is banker's rounding)."""
    return int(math.floor(v + 0.5))


@dataclass
class Prim:
    kind: str                 # rect | line | arc | text | outline
    color: RGB
    data: tuple


@dataclass
class Element:
    key: str
    prims: List[Prim] = field(default_factory=list)
    track: bool = False

    # convenience builders (coordinates in final pixels) -------------------------------
    def rect(self, x0: float, y0: float, x1: float, y1: float, color: RGB) -> "Element":
        self.prims.append(Prim("rect", color, (x0, y0, x1, y1)))
        return self

    def hline(self, x0: float, x1: float, y: float, lw: float, color: RGB) -> "Element":
        if x1 < x0:
            x0, x1 = x1, x0
        return self.rect(x0, y - lw / 2, x1, y + lw / 2, color)

    def vline(self, x: float, y0: float, y1: float, lw: float, color: RGB) -> "Element":
        if y1 < y0:
            y0, y1 = y1, y0
        return self.rect(x - lw / 2, y0, x + lw / 2, y1, color)

    def line(self, pts: Sequence[Tuple[float, float]], lw: float, color: RGB) -> "Element":
        self.prims.append(Prim("line", color, (tuple(pts), lw)))
        return self

    def arc(self, bbox: Box, start: float, end: float, lw: float, color: RGB) -> "Element":
        self.prims.append(Prim("arc", color, (bbox, start, end, lw)))
        return self

    def outline(self, x0: float, y0: float, x1: float, y1: float, lw: float, color: RGB) -> "Element":
        self.prims.append(Prim("outline", color, (x0, y0, x1, y1, lw)))
        return self

    def text(self, x: float, y: float, s: str, font: FontSpec, color: RGB, anchor: str = "ls") -> "Element":
        self.prims.append(Prim("text", color, (x, y, s, font, anchor)))
        return self


def text_bbox(s: str, font: FontSpec, ss: int, anchor: str = "ls") -> Box:
    """Ink-ish bbox of a string relative to its anchor point, in final pixels."""
    f = font.load(ss)
    l, t, r, b = f.getbbox(s, anchor=anchor)
    return l / ss, t / ss, r / ss, b / ss


def _draw(draw: ImageDraw.ImageDraw, p: Prim, ss: int, ox: int, oy: int, fill) -> None:
    """Draw one primitive; (ox, oy) is the patch origin in supersampled pixels."""
    if p.kind == "rect":
        x0, y0, x1, y1 = p.data
        i0, j0, i1, j1 = _r(x0 * ss) - ox, _r(y0 * ss) - oy, _r(x1 * ss) - ox, _r(y1 * ss) - oy
        if i1 <= i0:
            i1 = i0 + 1
        if j1 <= j0:
            j1 = j0 + 1
        draw.rectangle([i0, j0, i1 - 1, j1 - 1], fill=fill)
    elif p.kind == "outline":
        x0, y0, x1, y1, lw = p.data
        w = max(1, _r(lw * ss))
        i0, j0, i1, j1 = _r(x0 * ss) - ox, _r(y0 * ss) - oy, _r(x1 * ss) - ox, _r(y1 * ss) - oy
        draw.rectangle([i0, j0, i1 - 1, j1 - 1], outline=fill, width=w)
    elif p.kind == "line":
        pts, lw = p.data
        q = [(x * ss - ox, y * ss - oy) for x, y in pts]
        draw.line(q, fill=fill, width=max(1, _r(lw * ss)), joint="curve" if len(q) > 2 else None)
    elif p.kind == "arc":
        (x0, y0, x1, y1), start, end, lw = p.data
        draw.arc([x0 * ss - ox, y0 * ss - oy, x1 * ss - ox, y1 * ss - oy], start, end, fill=fill,
                 width=max(1, _r(lw * ss)))
    elif p.kind == "text":
        x, y, s, font, anchor = p.data
        draw.text((x * ss - ox, y * ss - oy), s, font=font.load(ss), fill=fill, anchor=anchor)
    else:  # pragma: no cover - programming error
        raise ValueError(p.kind)


def _prim_bounds(p: Prim, ss: int) -> Box:
    """Conservative bounds of a primitive in final pixels."""
    if p.kind == "rect":
        return p.data
    if p.kind == "outline":
        x0, y0, x1, y1, lw = p.data
        return x0 - lw, y0 - lw, x1 + lw, y1 + lw
    if p.kind == "line":
        pts, lw = p.data
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        return min(xs) - lw - 1, min(ys) - lw - 1, max(xs) + lw + 1, max(ys) + lw + 1
    if p.kind == "arc":
        (x0, y0, x1, y1), _, _, lw = p.data
        return x0 - lw - 1, y0 - lw - 1, x1 + lw + 1, y1 + lw + 1
    x, y, s, font, anchor = p.data
    l, t, r, b = text_bbox(s, font, ss, anchor)
    return x + l - 2, y + t - 2, x + r + 2, y + b + 2


@dataclass
class Ink:
    box: Box                         # [x0, y0, x1, y1] pixel edges, final pixels
    hull: np.ndarray                 # convex hull of the covered pixels (N x 2, pixel-edge coords)
    area: int                        # covered pixels


def _hull(points: np.ndarray) -> np.ndarray:
    """Andrew's monotone chain on a small point set."""
    pts = np.unique(points, axis=0)
    if len(pts) <= 2:
        return pts.astype(np.float32)
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(tuple(p))
    upper: List = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(tuple(p))
    return np.array(lower[:-1] + upper[:-1], dtype=np.float32)


def _ink_from_mask(mask: np.ndarray, ox: float, oy: float) -> Optional[Ink]:
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    pts = []
    for y in rows:
        xs = np.flatnonzero(mask[y])
        pts += [(xs[0], y), (xs[-1] + 1, y), (xs[0], y + 1), (xs[-1] + 1, y + 1)]
    hull = _hull(np.array(pts, dtype=np.float32)) + np.array([ox, oy], dtype=np.float32)
    box = (float(cols[0] + ox), float(rows[0] + oy), float(cols[-1] + 1 + ox), float(rows[-1] + 1 + oy))
    return Ink(box, hull, int(mask.sum()))


def rasterize(width: int, height: int, ss: int, bg: RGB, elements: Iterable[Element],
              skip: Optional[set] = None) -> Tuple[Image.Image, Dict[str, Ink]]:
    """Draw elements in order; return the final RGB image and the ink of every tracked element."""
    skip = skip or set()
    canvas = Image.new("RGB", (width * ss, height * ss), bg)
    draw = ImageDraw.Draw(canvas)
    inks: Dict[str, Ink] = {}
    for el in elements:
        if el.key not in skip:
            for p in el.prims:
                _draw(draw, p, ss, 0, 0, p.color)
        if not el.track or not el.prims:
            continue
        bounds = [_prim_bounds(p, ss) for p in el.prims]
        x0 = max(0, int(math.floor(min(b[0] for b in bounds))) - 2)
        y0 = max(0, int(math.floor(min(b[1] for b in bounds))) - 2)
        x1 = min(width, int(math.ceil(max(b[2] for b in bounds))) + 2)
        y1 = min(height, int(math.ceil(max(b[3] for b in bounds))) + 2)
        if x1 <= x0 or y1 <= y0:
            continue
        patch = Image.new("L", ((x1 - x0) * ss, (y1 - y0) * ss), 0)
        pd = ImageDraw.Draw(patch)
        for p in el.prims:
            _draw(pd, p, ss, x0 * ss, y0 * ss, 255)
        if ss > 1:
            patch = patch.reduce(ss)
        ink = _ink_from_mask(np.asarray(patch) > 0, x0, y0)
        if ink is not None:
            inks[el.key] = ink
    img = canvas.reduce(ss) if ss > 1 else canvas
    return img, inks
