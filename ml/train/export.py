"""Export a trained checkpoint to ONNX for backend/app/engines/yolo_onnx.py and verify it.

    python train/export.py --weights runs/pilot/weights/best.pt --imgsz 736 --out models/logiclens-yolov8n.onnx

The backend expects: one float32 input [1, 3, H, W] (static), one output [1, 4 + nc, N] with
cx, cy, w, h in letterboxed pixels and per-class sigmoid scores, class order = classes.json,
no NMS in the graph. This script checks all of that with onnxruntime, and that the ONNX output
matches the PyTorch model on the same input.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import numpy as np

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))


RUNS_DIR = ML_DIR / "runs"
DESCRIPTION = "LogicLens ladder-symbol detector (YOLOv8, synthetic dataset v2); classes = contract/classes.json"


def sanitize_metadata(path: Path) -> None:
    """Ultralytics writes the absolute dataset path into 'description'; replace it and drop any
    other value that looks like a local path."""
    import onnx
    model = onnx.load(str(path))
    for prop in model.metadata_props:
        if prop.key == "description":
            prop.value = DESCRIPTION
        elif prop.key == "args":
            prop.value = re.sub(r"'data': '[^']*'", "'data': None", prop.value)
    onnx.save(model, str(path))


def check_checkpoint(path: Path, allow_external: bool) -> None:
    """Ultralytics unpickles .pt files (code runs on load): only checkpoints train.py wrote under
    ml/runs are accepted unless the caller explicitly vouches for the file."""
    p = Path(path).resolve()
    if not p.is_file():
        raise SystemExit(f"checkpoint not found: {path}")
    if not allow_external and RUNS_DIR.resolve() not in p.parents:
        raise SystemExit(f"{path} is not under {RUNS_DIR}; pass --allow-external only for a checkpoint you trust")


def verify_onnx(path: Path, nc: int, imgsz: int) -> dict:
    import onnx
    import onnxruntime as ort

    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    custom = sorted({n.domain for n in model.graph.node if n.domain not in ("", "ai.onnx")})
    if custom:  # checked before onnxruntime ever loads the graph
        raise ExportCheckError(f"non-standard operator domains in the graph: {custom}")
    opset = max(o.version for o in model.opset_import if o.domain in ("", "ai.onnx"))
    ops = {n.op_type for n in model.graph.node}
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    outs = sess.get_outputs()
    x = np.random.default_rng(0).random((1, 3, imgsz, imgsz), dtype=np.float32)
    y = sess.run(None, {inp.name: x})[0]
    n_anchors = sum((imgsz // s) ** 2 for s in (8, 16, 32))
    report = {"opset": opset, "input": [inp.name, list(inp.shape), inp.type], "outputs": [[o.name, list(o.shape)] for o in outs],
              "output_shape": list(y.shape), "has_nms": "NonMaxSuppression" in ops, "nodes": len(model.graph.node),
              "size_bytes": path.stat().st_size, "metadata": {p.key: p.value for p in model.metadata_props}}
    scores = y[0, 4:]
    checks = [
        (12 <= opset <= 17, f"opset {opset} outside 12..17"),
        (list(inp.shape) == [1, 3, imgsz, imgsz], f"input shape {inp.shape} is not static [1, 3, {imgsz}, {imgsz}]"),
        (len(outs) == 1 and list(y.shape) == [1, 4 + nc, n_anchors], f"output {list(y.shape)} != [1, {4 + nc}, {n_anchors}]"),
        (not report["has_nms"], "NMS must not be part of the graph"),
        (bool(np.isfinite(y).all()), "non-finite outputs"),
        (scores.min() >= 0.0 and scores.max() <= 1.0, "class scores must already be sigmoid"),
    ]
    for ok, message in checks:  # explicit checks, not asserts: they must survive python -O
        if not ok:
            raise ExportCheckError(message)
    return report


class ExportCheckError(ValueError):
    """The exported model does not meet the backend contract."""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True, type=Path)
    ap.add_argument("--imgsz", type=int, default=736)
    ap.add_argument("--opset", type=int, default=12)
    ap.add_argument("--out", type=Path, default=ML_DIR / "models" / "logiclens-yolov8n.onnx")
    ap.add_argument("--allow-external", action="store_true",
                    help="accept a checkpoint from outside ml/runs (it is unpickled: only files you trust)")
    a = ap.parse_args(argv)
    if not 12 <= a.opset <= 17:
        ap.error("--opset must be 12..17")
    check_checkpoint(a.weights, a.allow_external)

    import torch
    from ultralytics import YOLO
    from generator.contract import NAMES, NC

    model = YOLO(str(a.weights))  # our own checkpoint (produced by train.py)
    names = [model.names[i] for i in range(len(model.names))]
    if names != NAMES:
        raise SystemExit("checkpoint class names differ from contract/classes.json")
    exported = Path(model.export(format="onnx", imgsz=a.imgsz, opset=a.opset, dynamic=False, simplify=False,
                                 nms=False, half=False, batch=1, device="cpu"))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exported, a.out)
    sanitize_metadata(a.out)
    report = verify_onnx(a.out, NC, a.imgsz)

    # fidelity: ONNX vs PyTorch on the same random input
    import onnxruntime as ort
    x = np.random.default_rng(1).random((1, 3, a.imgsz, a.imgsz), dtype=np.float32)
    sess = ort.InferenceSession(str(a.out), providers=["CPUExecutionProvider"])
    y_onnx = sess.run(None, {sess.get_inputs()[0].name: x})[0]
    net = model.model.eval()
    with torch.no_grad():
        y_pt = net(torch.from_numpy(x))
    y_pt = (y_pt[0] if isinstance(y_pt, (list, tuple)) else y_pt).numpy()
    report["max_abs_diff_vs_torch"] = float(np.abs(y_onnx - y_pt).max())
    report["max_abs_diff_scores"] = float(np.abs(y_onnx[0, 4:] - y_pt[0, 4:]).max())
    if report["max_abs_diff_scores"] >= 1e-3:
        raise ExportCheckError(f"ONNX scores differ from PyTorch by {report['max_abs_diff_scores']}")
    (a.out.with_suffix(".export.json")).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
