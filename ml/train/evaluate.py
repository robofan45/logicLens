"""Evaluate the exported detector on the test split: mAP50 / mAP50-95 overall and per class
(Ultralytics validator on the ONNX file) and CPU latency per image with the backend's pipeline.

    python train/evaluate.py --model models/logiclens-yolov8n.onnx --data data/v2/dataset.yaml
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def latency(model_path: Path, images, threads: int, warmup: int = 3):
    from PIL import Image
    from onnx_infer import OnnxDetector
    det = OnnxDetector(model_path, threads=threads)
    times = []
    for i, p in enumerate(images):
        img = Image.open(p).convert("RGB")
        t = time.perf_counter()
        det(img)
        dt = (time.perf_counter() - t) * 1000
        if i >= warmup:
            times.append(dt)
    times.sort()
    return {"threads": threads, "images": len(times), "mean_ms": round(statistics.fmean(times), 1),
            "p50_ms": round(times[len(times) // 2], 1), "p95_ms": round(times[int(len(times) * 0.95) - 1], 1),
            "impl": det.impl}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", type=Path, default=ML_DIR / "models" / "logiclens-yolov8n.onnx")
    ap.add_argument("--data", type=Path, default=ML_DIR / "data" / "v2" / "dataset.yaml")
    ap.add_argument("--split", default="test")
    ap.add_argument("--imgsz", type=int, default=736)
    ap.add_argument("--latency-images", type=int, default=60)
    ap.add_argument("--out", type=Path, default=ML_DIR / "models" / "metrics.json")
    ap.add_argument("--project", type=Path, default=ML_DIR / "runs")
    a = ap.parse_args(argv)

    import ultralytics.utils.torch_utils as tu
    from ultralytics import YOLO
    from generator.contract import NAMES

    tu.NUM_THREADS = 2
    model = YOLO(str(a.model), task="detect")
    t0 = time.time()
    m = model.val(data=str(a.data), split=a.split, imgsz=a.imgsz, batch=1, device="cpu", workers=0, conf=0.001,
                  iou=0.6, plots=True, project=str(a.project.resolve()), name=f"eval_{a.split}", exist_ok=True,
                  verbose=False)
    val_seconds = time.time() - t0
    box = m.box
    per_class = {}
    for k, cid in enumerate(m.ap_class_index):
        p, r, ap50, ap = box.class_result(k)
        per_class[NAMES[int(cid)]] = {"id": int(cid), "precision": round(float(p), 4), "recall": round(float(r), 4),
                                      "mAP50": round(float(ap50), 4), "mAP50-95": round(float(ap), 4),
                                      "instances": int(m.nt_per_class[int(cid)]) if hasattr(m, "nt_per_class") else None}
    split_dir = Path(a.data).resolve().parent / "images" / a.split
    images = sorted(split_dir.iterdir())[: a.latency_images]
    result = {
        "model": a.model.name, "split": a.split, "imgsz": a.imgsz,
        "overall": {"precision": round(float(box.mp), 4), "recall": round(float(box.mr), 4),
                    "mAP50": round(float(box.map50), 4), "mAP50-95": round(float(box.map), 4)},
        "per_class": per_class,
        "latency": [latency(a.model, images, 1), latency(a.model, images, 2)],
        "val_seconds": round(val_seconds, 1),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=1))
    worst = sorted(per_class.items(), key=lambda kv: kv[1]["mAP50-95"])[:8]
    print(json.dumps({"overall": result["overall"], "latency": result["latency"],
                      "weakest": {k: v["mAP50-95"] for k, v in worst}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
