"""ONNX inference exactly as the backend runs it (letterbox, /255, decode, class-wise NMS).

Uses backend/app/engines/yolo_onnx.py when importable so the numbers measured here are the
backend's; falls back to an identical local copy (kept in sync by tests/unit/test_onnx_infer.py).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
PAD_VALUE = 114


def _local_letterbox(img: Image.Image, new_hw: Tuple[int, int]):
    new_h, new_w = new_hw
    w, h = img.size
    ratio = min(new_w / w, new_h / h)
    unpad_w, unpad_h = int(round(w * ratio)), int(round(h * ratio))
    dw, dh = (new_w - unpad_w) / 2.0, (new_h - unpad_h) / 2.0
    resized = img if (unpad_w, unpad_h) == (w, h) else img.resize((unpad_w, unpad_h), Image.BILINEAR)
    canvas = Image.new("RGB", (new_w, new_h), (PAD_VALUE, PAD_VALUE, PAD_VALUE))
    canvas.paste(resized, (int(round(dw - 0.1)), int(round(dh - 0.1))))
    return np.asarray(canvas, dtype=np.uint8), ratio, (dw, dh)


def _local_nms(boxes, scores, iou_thres):
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = np.argsort(-scores, kind="stable")
    keep = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        xx1, yy1 = np.maximum(x1[i], x1[rest]), np.maximum(y1[i], y1[rest])
        xx2, yy2 = np.minimum(x2[i], x2[rest]), np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        order = rest[inter / (areas[i] + areas[rest] - inter + 1e-9) <= iou_thres]
    return keep


def _local_decode(output, conf_thres, iou_thres, ratio, pad, orig_size, nc, max_det=1000):
    out = np.asarray(output, dtype=np.float32)[0]
    preds = out.T if out.shape[0] == 4 + nc else out
    scores = preds[:, 4:]
    cls = scores.argmax(axis=1)
    conf = scores[np.arange(len(scores)), cls]
    mask = conf >= conf_thres
    preds, cls, conf = preds[mask], cls[mask], conf[mask]
    cx, cy, bw, bh = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    if len(xyxy) == 0:
        return []
    offset = cls[:, None].astype(np.float32) * (float(np.abs(xyxy).max()) + 1.0)
    keep = _local_nms(xyxy + offset, conf, iou_thres)[:max_det]
    dw, dh = pad
    width, height = orig_size
    dets = []
    for i in keep:
        x1, y1, x2, y2 = xyxy[i]
        x1 = min(max((x1 - dw) / ratio, 0.0), width)
        x2 = min(max((x2 - dw) / ratio, 0.0), width)
        y1 = min(max((y1 - dh) / ratio, 0.0), height)
        y2 = min(max((y2 - dh) / ratio, 0.0), height)
        if x2 - x1 >= 1 and y2 - y1 >= 1:
            dets.append((int(cls[i]), float(conf[i]), (float(x1), float(y1), float(x2), float(y2))))
    return _local_suppress_lookalikes(dets)


# Mirror of backend/app/engines/yolo_onnx.py::suppress_lookalikes (cross-class NMS inside the
# contact / coil / box families; rails and branch connectors are never merged).
_CONTACTS = {"XIC", "XIO", "P", "N", "LBL"}
_COILS = {"OTE", "OTL", "OTU", "NCOIL", "RES", "JMP", "MCR", "END"}


def _families():
    import json
    classes = json.loads((REPO / "contract" / "classes.json").read_text())["classes"]
    fam = {}
    for c in classes:
        m = c["mnemonic"]
        fam[c["id"]] = None if m is None else "contact" if m in _CONTACTS else "coil" if m in _COILS else "box"
    return fam


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _local_suppress_lookalikes(dets, iou_thres=0.5):
    fam = _families()
    kept = []
    for d in sorted(dets, key=lambda d: -d[1]):
        f = fam.get(d[0])
        if f is not None and any(fam.get(k[0]) == f and _iou(k[2], d[2]) >= iou_thres for k in kept):
            continue
        kept.append(d)
    return kept


def backend_functions():
    """(letterbox, decode) from the backend if importable, else the local copies."""
    try:
        sys.path.insert(0, str(REPO / "backend"))
        sys.dont_write_bytecode = True  # read-only use of backend/: leave no __pycache__ behind
        from app.engines.yolo_onnx import decode_yolov8, letterbox  # type: ignore

        def decode(output, conf_thres, iou_thres, ratio, pad, orig_size, nc):
            return [(d.class_id, d.confidence, d.bbox) for d in
                    decode_yolov8(output, conf_thres=conf_thres, iou_thres=iou_thres, ratio=ratio, pad=pad,
                                  orig_size=orig_size, nc=nc)]
        return letterbox, decode, "backend"
    except Exception:  # pragma: no cover - backend deps missing
        return _local_letterbox, _local_decode, "local"


class OnnxDetector:
    def __init__(self, path: Path, threads: int = 1, conf: float = 0.25, iou: float = 0.45):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        inp = self.sess.get_inputs()[0]
        self.name = inp.name
        self.hw = (int(inp.shape[2]), int(inp.shape[3]))
        self.nc = int(self.sess.get_outputs()[0].shape[1]) - 4
        self.conf, self.iou = conf, iou
        self.letterbox, self.decode, self.impl = backend_functions()

    def __call__(self, image: Image.Image, conf: Optional[float] = None):
        arr, ratio, pad = self.letterbox(image.convert("RGB"), self.hw)
        x = np.ascontiguousarray(arr.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        out = self.sess.run(None, {self.name: x})[0]
        return self.decode(out, conf if conf is not None else self.conf, self.iou, ratio, pad, image.size, self.nc)
