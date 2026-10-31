"""YOLOv8 ONNX detector (onnxruntime, CPU) and the Ultralytics output decoder.

Ultralytics exports a detector as ``output0`` with shape [1, 4 + nc, N]: rows 0-3 are the box
centre/size (cx, cy, w, h) in letterboxed input pixels, rows 4.. are per-class scores (already
sigmoid). The transposed layout [1, N, 4 + nc] is accepted too. Decoding = threshold, class-wise
NMS, undo the letterbox, clip to the source image.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from .. import __version__
from ..errors import ApiError
from ..gate import Gates
from ..program import finalize_rungs, guess_platform
from ..schemas import EngineInfo, Program
from ..vendor.logiclens_ladder import parse_program
from .assembler import assemble
from .base import CLASS_BY_ID, NC, Detection
from .ocr import Ocr

log = logging.getLogger("logiclens.yolo")

PAD_VALUE = 114


def letterbox(img: Image.Image, new_hw: Tuple[int, int]) -> Tuple[np.ndarray, float, Tuple[float, float]]:
    """Resize keeping aspect ratio and pad to new_hw (Ultralytics convention, centred padding)."""
    new_h, new_w = new_hw
    w, h = img.size
    ratio = min(new_w / w, new_h / h)
    unpad_w, unpad_h = int(round(w * ratio)), int(round(h * ratio))
    dw, dh = (new_w - unpad_w) / 2.0, (new_h - unpad_h) / 2.0
    resized = img if (unpad_w, unpad_h) == (w, h) else img.resize((unpad_w, unpad_h), Image.BILINEAR)
    canvas = Image.new("RGB", (new_w, new_h), (PAD_VALUE, PAD_VALUE, PAD_VALUE))
    canvas.paste(resized, (int(round(dw - 0.1)), int(round(dh - 0.1))))
    return np.asarray(canvas, dtype=np.uint8), ratio, (dw, dh)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> List[int]:
    """Greedy non-maximum suppression; returns kept indices in descending score order."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = np.argsort(-scores, kind="stable")  # ties keep anchor order: deterministic output
    keep: List[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thres]
    return keep


def decode_yolov8(output: np.ndarray, *, conf_thres: float, iou_thres: float, ratio: float,
                  pad: Sequence[float], orig_size: Tuple[int, int], nc: int = NC, max_det: int = 1000,
                  pre_nms_topk: int = 30_000) -> List[Detection]:
    out = np.asarray(output, dtype=np.float32)
    if out.ndim == 3:
        out = out[0]
    if out.ndim != 2:
        raise ValueError(f"unexpected YOLO output rank {out.ndim}; expected [1, {4 + nc}, N]")
    if out.shape[0] == 4 + nc:
        preds = out.T
    elif out.shape[1] == 4 + nc:
        preds = out
    else:
        raise ValueError(f"YOLO output {tuple(np.shape(output))} does not match classes.json "
                         f"({nc} classes -> [1, {4 + nc}, N])")
    if preds.shape[0] == 0:
        return []
    scores = preds[:, 4:]
    cls = scores.argmax(axis=1)
    conf = scores[np.arange(len(scores)), cls]
    mask = conf >= conf_thres
    if not mask.any():
        return []
    preds, cls, conf = preds[mask], cls[mask], conf[mask]
    if len(conf) > pre_nms_topk:
        top = np.argpartition(-conf, pre_nms_topk)[:pre_nms_topk]
        preds, cls, conf = preds[top], cls[top], conf[top]
    cx, cy, bw, bh = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    xyxy = np.stack([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], axis=1)
    offset = cls[:, None].astype(np.float32) * (float(np.abs(xyxy).max()) + 1.0)  # class-wise NMS
    keep = nms(xyxy + offset, conf, iou_thres)[:max_det]
    dw, dh = float(pad[0]), float(pad[1])
    width, height = orig_size
    dets = []
    for i in keep:
        x1, y1, x2, y2 = xyxy[i]
        x1 = min(max((x1 - dw) / ratio, 0.0), width)
        x2 = min(max((x2 - dw) / ratio, 0.0), width)
        y1 = min(max((y1 - dh) / ratio, 0.0), height)
        y2 = min(max((y2 - dh) / ratio, 0.0), height)
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        dets.append(Detection(int(cls[i]), float(conf[i]), (float(x1), float(y1), float(x2), float(y2))))
    return suppress_lookalikes(dets)


# Classes that are drawn alike (contacts, coils, boxes that differ only by the text inside) can
# fire on the same symbol. Class-wise NMS keeps both, which the assembler would read as two
# instructions in series. Suppress across classes within a family, keeping the best score.
_CONTACTS = {"XIC", "XIO", "P", "N", "LBL"}
_COILS = {"OTE", "OTL", "OTU", "NCOIL", "RES", "JMP", "MCR", "END"}


def _family(class_id: int) -> Optional[str]:
    info = CLASS_BY_ID.get(class_id)
    m = info.mnemonic if info else None
    if m is None:
        return None  # rails, branch connectors: never merged across classes
    if m in _CONTACTS:
        return "contact"
    if m in _COILS:
        return "coil"
    return "box"


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def suppress_lookalikes(dets: List[Detection], iou_thres: float = 0.5) -> List[Detection]:
    """Cross-class NMS inside each look-alike family; structural classes pass through."""
    kept: List[Detection] = []
    for d in sorted(dets, key=lambda d: -d.confidence):
        fam = _family(d.class_id)
        if fam is not None and any(_family(k.class_id) == fam and _iou(k.bbox, d.bbox) >= iou_thres for k in kept):
            continue
        kept.append(d)
    return kept


class YoloOnnxDetector:
    """One onnxruntime CPU session per worker process. ``InferenceSession.run`` is thread-safe."""

    def __init__(self, model_path: Path, *, conf: float = 0.25, iou: float = 0.45, imgsz: int = 640,
                 threads: int = 1, max_det: int = 1000):
        import onnxruntime as ort

        so = ort.SessionOptions()
        if threads > 0:
            so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
        self.model_name = Path(model_path).name
        self.conf, self.iou, self.max_det = conf, iou, max_det
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = list(inp.shape)
        h = shape[2] if len(shape) == 4 and isinstance(shape[2], int) else imgsz
        w = shape[3] if len(shape) == 4 and isinstance(shape[3], int) else imgsz
        self.input_hw = (int(h), int(w))
        out_shape = list(self.session.get_outputs()[0].shape)
        static = [d for d in out_shape[1:] if isinstance(d, int)]
        if len(out_shape) == 3 and len(static) == 2 and 4 + NC not in static:
            raise ValueError(f"model output {out_shape} does not match classes.json ({NC} classes -> "
                             f"[1, {4 + NC}, N]); retrain/export with contract/classes.json")

    def detect(self, image: Image.Image) -> List[Detection]:
        arr, ratio, pad = letterbox(image, self.input_hw)
        x = np.ascontiguousarray(arr.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        output = self.session.run(None, {self.input_name: x})[0]
        return decode_yolov8(output, conf_thres=self.conf, iou_thres=self.iou, ratio=ratio, pad=pad,
                             orig_size=image.size, max_det=self.max_det)


def model_candidates(path: Optional[Path]) -> Optional[Path]:
    """The configured model file if it exists."""
    if path is None:
        return None
    p = Path(path)
    return p if p.is_file() else None


# ============================================================================ engine


class DetectorLoader:
    """Loads the ONNX session once per worker process, on first use (or at warm-up), thread-safely.
    A model that fails to load is reported once and not retried until the process restarts."""

    def __init__(self, settings, factory=None):
        self.path = Path(settings.yolo_onnx) if settings.yolo_onnx else None
        self._factory = factory or (lambda p: YoloOnnxDetector(
            p, conf=settings.yolo_conf, iou=settings.yolo_iou, imgsz=settings.yolo_imgsz, threads=settings.yolo_threads))
        self._detector = None
        self._error: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def model_name(self) -> Optional[str]:
        return self.path.name if self.path else None

    def available(self) -> bool:
        return self.path is not None and self.path.is_file() and self._error is None

    def reason(self) -> Optional[str]:
        if self.path is None:
            return "LOGICLENS_YOLO_ONNX is not set"
        if not self.path.is_file():
            return f"the model file '{self.path.name}' was not found (LOGICLENS_YOLO_ONNX)"
        if self._error:
            return f"the model '{self.path.name}' failed to load ({self._error}); check LOGICLENS_YOLO_ONNX"
        return None

    def get(self):
        if self._detector is not None:
            return self._detector
        with self._lock:
            if self._detector is None:
                if not self.available():
                    raise ApiError(503, "E_ENGINE_UNAVAILABLE", f"The YOLO engine is unavailable: {self.reason()}.")
                try:
                    self._detector = self._factory(self.path)
                except Exception as exc:  # any load failure makes the engine unavailable, never a 500
                    self._error = type(exc).__name__
                    log.error("YOLO model %s failed to load: %s", self.path.name, exc)
                    raise ApiError(503, "E_ENGINE_UNAVAILABLE",
                                   f"The YOLO engine is unavailable: {self.reason()}.") from None
        return self._detector


class YoloEngine:
    name = "yolo-onnx"
    uses_llm = False

    def __init__(self, loader: DetectorLoader, ocr: Optional[Ocr], gates: Gates):
        self.loader = loader
        self.ocr = ocr
        self.gates = gates

    def available(self) -> bool:
        return self.loader.available()

    def unavailable_reason(self) -> Optional[str]:
        return self.loader.reason()

    def detect(self, image: Image.Image) -> List[Detection]:
        return self.loader.get().detect(image)

    def build_program(self, image: Image.Image, detections: List[Detection], platform: Optional[str],
                      warnings: Sequence[str] = ()) -> Program:
        started = time.perf_counter()
        result = assemble(image, detections, self.ocr)
        all_warnings = list(warnings) + result.warnings
        rungs = finalize_rungs(result.rungs, all_warnings)
        if platform:
            chosen, confidence = platform, 100.0
        else:
            chosen, confidence = guess_platform(parse_program("\n".join(r.text for r in rungs)).rungs)
        return Program(source="image", platform=chosen, platform_confidence=confidence, rungs=rungs,
                       detections=[d.to_out() for d in detections[:5000]], warnings=all_warnings,
                       engine=EngineInfo(name="yolo-onnx", version=__version__, model=self.loader.model_name),
                       timing_ms={"assemble": (time.perf_counter() - started) * 1000})

    def parse(self, image: Image.Image, platform: Optional[str]) -> Program:
        with self.gates.cpu.slot():
            started = time.perf_counter()
            detections = self.detect(image)
            inference = (time.perf_counter() - started) * 1000
            program = self.build_program(image, detections, platform)
        program.timing_ms = {"inference": inference, **(program.timing_ms or {})}
        return program
