"""Generate the LogicLens synthetic ladder dataset (Ultralytics layout + per-image metadata).

    python -m generator.generate --out data/v2 --n-train 2000 --n-val 300 --n-test 300 --seed 1 \\
        --imgsz-hint 736

Writes  OUT/images/{train,val,test}/*.png|jpg   OUT/labels/{split}/*.txt (YOLO, class cx cy w h)
        OUT/meta/{split}/*.json (LLT ground truth, style, boxes of every instruction and its text)
        OUT/dataset.yaml (44 names in contract/classes.json order)   OUT/report.json
        OUT/preview_{split}.png (labels drawn)   OUT/preview_crops_{split}.png (zoomed symbol boxes)

Deterministic for a seed: a sample depends only on (seed, split, index), so --workers changes
speed, never content. Default --workers 0 runs in-process (gentle on shared machines).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

if __package__ in (None, ""):  # allow `python generator/generate.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "generator"  # noqa: A001

from .contract import NAMES, NC, SYMBOL_IDS  # noqa: E402
from .dataset import (SPLITS, Sample, class_histogram, dataset_yaml, encode_image, make_sample,  # noqa: E402
                      meta_json, yolo_lines)
from .preview import contact_sheet, crop_sheet  # noqa: E402

_MANAGED = ("images", "labels", "meta")
_MANAGED_FILES = ("dataset.yaml", "report.json", "preview_train.png", "preview_val.png", "preview_test.png",
                  "preview_crops_train.png", "preview_crops_val.png", "preview_crops_test.png")


def _prepare_out(out: Path, overwrite: bool) -> None:
    out = out.resolve()
    if out == Path(out.anchor) or out == Path.home().resolve():
        raise SystemExit(f"refusing to write a dataset into {out}")
    if out.exists() and not out.is_dir():
        raise SystemExit(f"{out} exists and is not a directory")
    existing = [p for p in out.iterdir()] if out.exists() else []
    if existing and not overwrite:
        raise SystemExit(f"{out} is not empty; pass --overwrite to replace a previous dataset there")
    if overwrite:  # only ever delete what this tool creates
        for name in _MANAGED:
            p = out / name
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
        for name in _MANAGED_FILES:
            p = out / name
            if p.is_file():
                p.unlink()
    for name in _MANAGED:
        for split in SPLITS:
            (out / name / split).mkdir(parents=True, exist_ok=True)


def _job(args):
    seed, split, index, imgsz = args
    s = make_sample(seed, split, index, imgsz)
    return s.split, s.index, s.stem, s.ext, encode_image(s), yolo_lines(s.labels, *s.meta["size"]), meta_json(s), \
        s.labels, s.meta


def _iter_jobs(jobs, workers: int):
    if workers <= 0:
        for j in jobs:
            yield _job(j)
        return
    import multiprocessing as mp
    with mp.get_context("spawn").Pool(workers) as pool:
        yield from pool.imap(_job, jobs, chunksize=4)


def generate(out: Path, n: Dict[str, int], seed: int, imgsz_hint: int, workers: int = 0, overwrite: bool = False,
             preview: int = 12, log=print) -> dict:
    out = Path(out)
    _prepare_out(out, overwrite)
    started = time.time()
    report: dict = {"seed": seed, "imgsz_hint": imgsz_hint, "counts": {}, "class_histogram": {}, "styles": {},
                    "platforms": {}, "augment": {}, "image_size": {}, "symbol_px_at_imgsz": {}}
    for split in SPLITS:
        jobs = [(seed, split, i, imgsz_hint) for i in range(n.get(split, 0))]
        label_sets: List[list] = []
        previews = []
        styles: Dict[str, int] = {}
        plats: Dict[str, int] = {}
        augs: Dict[str, int] = {}
        sizes, eff = [], []
        t0 = time.time()
        for k, (sp, idx, stem, ext, img_bytes, lines, meta_text, labels, meta) in enumerate(_iter_jobs(jobs, workers)):
            (out / "images" / sp / (stem + ext)).write_bytes(img_bytes)
            (out / "labels" / sp / (stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            (out / "meta" / sp / (stem + ".json")).write_text(meta_text, encoding="utf-8")
            label_sets.append(labels)
            styles[meta["style"]] = styles.get(meta["style"], 0) + 1
            plats[meta["platform"]] = plats.get(meta["platform"], 0) + 1
            augs[meta["augment"]["level"]] = augs.get(meta["augment"]["level"], 0) + 1
            w, h = meta["size"]
            sizes.append(max(w, h))
            sym_h = [b[4] - b[2] for b in labels if b[0] in (0, 1)]
            if sym_h:
                eff.append(min(sym_h) * imgsz_hint / max(w, h))
            if len(previews) < preview:
                from PIL import Image
                import io
                previews.append((Image.open(io.BytesIO(img_bytes)).convert("RGB"), labels,
                                 f"{stem} {meta['style']}/{meta['platform']} aug={meta['augment']['level']}"))
            if log and (k + 1) % 100 == 0:
                rate = (k + 1) / max(1e-9, time.time() - t0)
                log(f"  {split}: {k + 1}/{len(jobs)} ({rate:.1f} img/s)")
        hist = class_histogram(label_sets)
        report["counts"][split] = len(jobs)
        report["class_histogram"][split] = {NAMES[i]: hist[i] for i in range(NC)}
        report["styles"][split] = styles
        report["platforms"][split] = plats
        report["augment"][split] = augs
        if sizes:
            report["image_size"][split] = {"min": min(sizes), "median": statistics.median(sizes), "max": max(sizes)}
        if eff:
            report["symbol_px_at_imgsz"][split] = {"min": round(min(eff), 2), "p05": round(sorted(eff)[len(eff) // 20], 2),
                                                   "median": round(statistics.median(eff), 2)}
        if previews:
            contact_sheet(previews, cols=3).save(out / f"preview_{split}.png")
            crop_sheet([(p[0], p[1]) for p in previews], n=60, seed=seed).save(out / f"preview_crops_{split}.png")
        if log:
            log(f"{split}: {len(jobs)} images in {time.time() - t0:.1f}s")
    (out / "dataset.yaml").write_text(dataset_yaml(str(out.resolve())), encoding="utf-8")
    train_hist = report["class_histogram"].get("train", {})
    symbol_counts = {NAMES[i]: train_hist.get(NAMES[i], 0) for i in SYMBOL_IDS}
    report["train_symbol_min"] = min(symbol_counts.items(), key=lambda kv: kv[1]) if symbol_counts else None
    report["seconds"] = round(time.time() - started, 1)
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="output dataset folder")
    ap.add_argument("--n-train", type=int, default=2000)
    ap.add_argument("--n-val", type=int, default=300)
    ap.add_argument("--n-test", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--imgsz-hint", type=int, default=736,
                    help="training image size; canvases are sized so the smallest symbol stays >= 14 px after "
                         "letterboxing to it")
    ap.add_argument("--workers", type=int, default=0, help="worker processes (0 = in-process)")
    ap.add_argument("--preview", type=int, default=12, help="images per split in the preview contact sheets")
    ap.add_argument("--overwrite", action="store_true", help="replace a dataset previously generated in --out")
    a = ap.parse_args(argv)
    for name in ("n_train", "n_val", "n_test"):
        if getattr(a, name) < 0:
            ap.error(f"--{name.replace('_', '-')} must be >= 0")
    if not 64 <= a.imgsz_hint <= 4096:
        ap.error("--imgsz-hint must be in 64..4096")
    report = generate(a.out, {"train": a.n_train, "val": a.n_val, "test": a.n_test}, a.seed, a.imgsz_hint,
                      workers=a.workers, overwrite=a.overwrite, preview=a.preview)
    print(json.dumps({k: report[k] for k in ("counts", "train_symbol_min", "seconds", "symbol_px_at_imgsz")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
