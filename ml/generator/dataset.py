"""One synthetic sample end to end: program -> render -> (augment) -> YOLO labels + metadata.

Determinism: every sample draws all its randomness from ``random.Random("<seed>:<split>:<index>")``
(string seeds hash with SHA-512, independent of PYTHONHASHSEED), so a sample depends only on
(seed, split, index) - not on generation order or worker count.

Disjoint splits by construction: the split of a sample is fixed by a hash of its ground-truth
program text (rung texts, comments excluded). A candidate whose hash bucket belongs to another
split is rejected and resampled, so no program text can ever appear in two splits.
"""
from __future__ import annotations

import hashlib
import io
import json
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from . import __version__
from .augment import augment
from .compose import Composer, Composition
from .contract import (BRANCH_END, BRANCH_START, DEPRECATED_IDS, EMITTED_IDS, NAMES, NC, RAIL_LEFT, RAIL_RIGHT,
                       SYMBOL_IDS, llt)
from .sampler import ProgramSampler
from .styles import choose_style_and_platform, sample_style

SPLITS = ("train", "val", "test")
SPLIT_BUCKETS = {"train": range(0, 80), "val": range(80, 90), "test": range(90, 100)}
AUG_LEVELS = (("none", 0.35), ("light", 0.40), ("heavy", 0.25))
MIN_STRUCT_W = 6.0
END_RATE = 0.45          # rockwell programs that end (in view) with an END rung
ZOOM_RATE = 0.25         # images drawn on a smaller canvas (larger symbols after letterboxing)
TEXT_ROLES_FOR_OCR = ("operand", "bit", "box_title", "box_desc", "box_row", "box_value")


def program_key(rung_texts: List[str]) -> str:
    return "\n".join(rung_texts)


def split_of(rung_texts: List[str]) -> str:
    h = int(hashlib.sha256(program_key(rung_texts).encode("utf-8")).hexdigest()[:8], 16) % 100
    for name, rng_ in SPLIT_BUCKETS.items():
        if h in rng_:
            return name
    raise AssertionError("unreachable")  # pragma: no cover


@dataclass
class Sample:
    split: str
    index: int
    stem: str
    image: Image.Image
    labels: List[Tuple[int, float, float, float, float]]     # class, x0, y0, x1, y1 (pixels)
    meta: dict
    ext: str = ".png"
    jpeg_quality: Optional[int] = None


def _rng(seed: int, split: str, index: int) -> random.Random:
    return random.Random(f"logiclens-v2:{seed}:{split}:{index}")  # nosec B311 - synthetic data, not security


def _widen(box, min_w: float, width: int):
    x0, y0, x1, y1 = box
    if x1 - x0 >= min_w:
        return [x0, y0, x1, y1]
    c = (x0 + x1) / 2
    x0, x1 = max(0.0, c - min_w / 2), min(float(width), c + min_w / 2)
    if x1 - x0 < min_w:  # against an image edge
        x0, x1 = (0.0, min_w) if x0 <= 0 else (width - min_w, float(width))
    return [x0, y0, x1, y1]


def plan_sample(seed: int, split: str, index: int, imgsz_hint: int = 736, max_attempts: int = 400):
    """The accepted layout plan of a sample (no rasterising). Returns (rng, composer, plan)."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}")
    rng = _rng(seed, split, index)
    for _attempt in range(max_attempts):
        style_name, platform = choose_style_and_platform(rng)
        style = sample_style(style_name, rng, platform)
        sampler = ProgramSampler(platform, rng, comment_rate=style.comment_rate)
        program = sampler.sample(rng.randint(3, 9))
        want_end = platform.startswith("rockwell") and rng.random() < END_RATE
        zoom = rng.uniform(0.45, 0.85) if rng.random() < ZOOM_RATE else 1.0
        composer = Composer(style, platform, rng, imgsz_hint, canvas_scale=zoom)
        plan = composer.plan(program.text(), want_end)
        if plan is None:
            continue
        if split_of(plan.rung_texts) != split:
            continue
        return rng, composer, plan
    raise RuntimeError(f"could not build sample {split}/{index} in {max_attempts} attempts")  # pragma: no cover


def make_sample(seed: int, split: str, index: int, imgsz_hint: int = 736, aug: Optional[str] = None) -> Sample:
    """Build sample ``index`` of ``split``. ``aug`` forces an augmentation level (tests)."""
    rng, composer, plan = plan_sample(seed, split, index, imgsz_hint)
    comp = composer.render(plan)
    return _finish(seed, split, index, rng, comp, imgsz_hint, aug)


def _finish(seed: int, split: str, index: int, rng: random.Random, comp: Composition, imgsz_hint: int,
            aug: Optional[str]) -> Sample:
    level = aug or rng.choices([a for a, _ in AUG_LEVELS], [w for _, w in AUG_LEVELS])[0]
    width, height = comp.size
    image = comp.image
    jpeg_q = None
    aug_params: dict = {"level": "none"}
    boxes: Dict[str, Optional[Tuple[float, float, float, float]]]
    if level == "none":
        boxes = {k: tuple(v) for k, v in _clean_boxes(comp).items()}
    else:
        res = augment(image, comp.hulls, rng, level, comp.style.bg)
        image, boxes, aug_params, jpeg_q = res.image, res.boxes, res.params, res.jpeg_quality
        width, height = res.size

    def get(key: str):
        b = boxes.get(key)
        return None if b is None else [round(float(v), 2) for v in b]

    labels: List[Tuple[int, float, float, float, float]] = []
    instructions = []
    for ins in comp.instructions:
        box = get(ins["key"])
        rec = {k: v for k, v in ins.items() if k not in ("key", "box", "texts", "line_y")}
        rec["class_name"] = NAMES[ins["class_id"]]
        rec["box"] = box
        rec["visible"] = box is not None
        rec["texts"] = [{"role": t["role"], "text": t["text"], "box": get(t["key"])} for t in ins["texts"]]
        instructions.append(rec)
        if box is not None:
            labels.append((ins["class_id"], *box))
    structures = []
    for st in comp.structures:
        box = get(st["key"])
        if box is not None:
            box = [round(v, 2) for v in _widen(box, MIN_STRUCT_W, width)]
            labels.append((st["class_id"], *box))
        structures.append({"class_id": st["class_id"], "class_name": NAMES[st["class_id"]], "rung": st["rung"],
                           "box": box, "visible": box is not None})
    decor = [{"role": d["role"], "text": d["text"], "box": get(d["key"])} for d in comp.decor]
    rung_meta = []
    for rp, band in zip(comp.rungs, comp.rung_bands):
        rung_meta.append({
            "index": rp.index, "number": comp.style.rung_num_start + rp.index if comp.style.rung_label != "network"
            else comp.style.rung_num_start + rp.index + 1,
            "text": rp.rung.text, "comment": rp.rung.comment if rp.comment_lines else None,
            "band": get(f"band:{rp.index}"),
            "instructions": [i for i, ins in enumerate(comp.instructions) if ins["rung"] == rp.index],
        })
    stem = f"{split}_{index:06d}"
    ext = ".jpg" if jpeg_q else ".png"
    s = comp.style
    meta = {
        "format": "logiclens-synth", "generator_version": __version__, "image": stem + ext, "split": split,
        "seed": seed, "index": index, "size": [width, height], "imgsz_hint": imgsz_hint,
        "style": s.name, "platform": comp.platform, "symbol_family": s.family, "symbol_height_px": s.u,
        "augment": aug_params, "llt": comp.program_text, "rungs": rung_meta, "instructions": instructions,
        "structures": structures, "decor": decor,
        "style_params": {"ss": s.ss, "split_address": s.split_address, "coil_shape": s.coil_shape,
                         "fonts": [s.f_op.path and s.f_op.path.rsplit("/", 1)[-1], s.f_box.path and s.f_box.path.rsplit("/", 1)[-1]],
                         "highlight": bool(s.highlight), "stubs": s.stubs, "rung_label": s.rung_label},
    }
    return Sample(split, index, stem, image, labels, meta, ext, jpeg_q)


def _clean_boxes(comp: Composition) -> Dict[str, Tuple[float, float, float, float]]:
    out: Dict[str, Tuple[float, float, float, float]] = {}
    for ins in comp.instructions:
        out[ins["key"]] = tuple(ins["box"])
        for t in ins["texts"]:
            out[t["key"]] = tuple(t["box"])
    for st in comp.structures:
        out[st["key"]] = tuple(st["box"])
    for d in comp.decor:
        out[d["key"]] = tuple(d["box"])
    for band in comp.rung_bands:
        out[f"band:{band['rung']}"] = tuple(band["band"])
    return out


def yolo_lines(labels, width: int, height: int) -> List[str]:
    lines = []
    for cid, x0, y0, x1, y1 in labels:
        if cid in DEPRECATED_IDS or cid not in EMITTED_IDS:
            raise ValueError(f"class {cid} must never be emitted")
        x0, x1 = max(0.0, min(width, x0)), max(0.0, min(width, x1))
        y0, y1 = max(0.0, min(height, y0)), max(0.0, min(height, y1))
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        cx, cy = (x0 + x1) / 2 / width, (y0 + y1) / 2 / height
        w, h = (x1 - x0) / width, (y1 - y0) / height
        lines.append(f"{cid} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return lines


def encode_image(sample: Sample) -> bytes:
    buf = io.BytesIO()
    if sample.ext == ".jpg":
        sample.image.save(buf, format="JPEG", quality=95, subsampling=0)
    else:
        sample.image.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def dataset_yaml(root: str, names: Optional[List[str]] = None) -> str:
    names = names or NAMES
    lines = [
        "# LogicLens synthetic ladder-logic dataset v2 (generated by ml/generator/generate.py)",
        f"path: {json.dumps(root)}", "train: images/train", "val: images/val", "test: images/test", f"nc: {len(names)}",
        "names:",
    ]
    lines += [f"  {i}: {n}" for i, n in enumerate(names)]
    return "\n".join(lines) + "\n"


def meta_json(sample: Sample) -> str:
    return json.dumps(sample.meta, indent=1, ensure_ascii=False, sort_keys=False)


def class_histogram(label_sets: List[List[Tuple[int, float, float, float, float]]]) -> Dict[int, int]:
    hist = {i: 0 for i in range(NC)}
    for labels in label_sets:
        for cid, *_ in labels:
            hist[cid] += 1
    return hist
