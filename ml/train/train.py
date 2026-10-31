"""Train the LogicLens detector (Ultralytics YOLOv8) with a hard wall-clock budget.

CPU pilot (what produced ml/models/logiclens-yolov8n.onnx):
    nice -n 15 python train/train.py --data data/v2/dataset.yaml --hours 1.6 --imgsz 736 --batch 8 \
        --threads 2 --name pilot

GPU production run (see ml/README.md):
    python train/train.py --data data/v2-20k/dataset.yaml --device 0 --hours 0 --epochs 150 --imgsz 1024 \
        --batch 32 --nbs 64 --workers 8 --name prod

Security: Ultralytics loads *.pt checkpoints with pickle (arbitrary code on load). Pretrained
weights are therefore only accepted when their SHA-256 matches PINNED_WEIGHTS (or --allow-unpinned
for a file you produced yourself).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent

# SHA-256 of the official Ultralytics release asset
# https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt (downloaded 2026-10-31)
PINNED_WEIGHTS = {
    "yolov8n.pt": "f59b3d833e2ff32e194b5bb8e08d211dc7c5bdf144b90d2c8412c47ccfc83b36",
}

# Ladder diagrams are not mirror-symmetric (left/right rails, Branch_Start vs Branch_End, the slash of
# an NC contact), so flips are off; rotation/perspective come from the generator, not from here.
HYP = dict(
    optimizer="AdamW", lr0=0.002, lrf=0.05, momentum=0.9, weight_decay=0.0005, warmup_epochs=0.5,
    warmup_bias_lr=0.01, cos_lr=False, fliplr=0.0, flipud=0.0, mosaic=1.0, close_mosaic=1, mixup=0.0,
    copy_paste=0.0, degrees=0.0, shear=0.0, perspective=0.0, translate=0.1, scale=0.3, hsv_h=0.015,
    hsv_s=0.4, hsv_v=0.3, erasing=0.0,
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_weights(path: Path, allow_unpinned: bool) -> None:
    if path.suffix != ".pt":
        return  # a model yaml: built from scratch, nothing is unpickled
    if not path.is_file():
        raise SystemExit(f"weights not found: {path}")
    want = PINNED_WEIGHTS.get(path.name)
    got = sha256(path)
    if want and got != want:
        raise SystemExit(f"{path.name}: SHA-256 {got} does not match the pinned {want}; refusing to unpickle it")
    if not want and not allow_unpinned:
        raise SystemExit(f"{path.name} is not pinned; pass --allow-unpinned only for checkpoints you produced")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--model", type=Path, default=ML_DIR / "train" / "weights" / "yolov8n.pt",
                    help="pretrained .pt (hash-pinned) or a model yaml such as yolov8n.yaml")
    ap.add_argument("--imgsz", type=int, default=736)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--nbs", type=int, default=16, help="nominal batch size (gradient accumulation target)")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hours", type=float, default=1.6, help="wall-clock budget; 0 = use --epochs")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--threads", type=int, default=2, help="torch CPU threads (Ultralytics would use cores-1)")
    ap.add_argument("--project", type=Path, default=ML_DIR / "runs")
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--allow-unpinned", action="store_true")
    a = ap.parse_args(argv)

    check_weights(a.model, a.allow_unpinned)
    os.environ.setdefault("OMP_NUM_THREADS", str(a.threads))
    import torch
    import ultralytics.utils.torch_utils as tu
    from ultralytics import YOLO

    tu.NUM_THREADS = a.threads          # select_device() resets torch threads to this on CPU
    torch.set_num_threads(a.threads)

    started = time.time()
    model = YOLO(str(a.model))
    kwargs = dict(data=str(a.data.resolve()), imgsz=a.imgsz, epochs=a.epochs, batch=a.batch, nbs=a.nbs,
                  device=a.device, workers=a.workers, project=str(a.project.resolve()), name=a.name, exist_ok=True,
                  seed=a.seed, deterministic=True, patience=1000, cache=False, plots=True, amp=a.device != "cpu",
                  val=True, verbose=True, **HYP)
    if a.hours > 0:
        kwargs["time"] = a.hours
    model.train(**kwargs)
    wall = time.time() - started
    run_dir = a.project.resolve() / a.name
    summary = {"args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(a).items()}, "hyp": HYP,
               "wall_seconds": round(wall, 1), "torch": torch.__version__, "best": str(run_dir / "weights" / "best.pt")}
    import ultralytics
    summary["ultralytics"] = ultralytics.__version__
    (run_dir / "train_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
