"""Hybrid engine: YOLO finds the symbols, Claude reads the diagram with those detections as hints.

Claude's transcription is authoritative for the text; element boxes are snapped to the matching
YOLO detection (YOLO boxes are tighter). Each half degrades to the other: if the detector fails,
Claude runs without hints; if Claude fails or is busy, the YOLO + OCR result is returned with a warning.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from PIL import Image

from ..errors import ApiError
from ..gate import Gates
from ..schemas import Program
from .base import Detection
from .claude_vision import ClaudeVisionEngine
from .yolo_onnx import YoloEngine

log = logging.getLogger("logiclens.hybrid")


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def snap_boxes(program: Program, detections: List[Detection]) -> int:
    """Replace each element box with the best-overlapping unused YOLO detection of the same mnemonic."""
    used = set()
    snapped = 0
    for rung in program.rungs:
        for el in rung.elements:
            if not el.bbox:
                continue
            best, best_iou = None, 0.05
            for i, d in enumerate(detections):
                if i in used or d.mnemonic != el.mnemonic:
                    continue
                iou = _iou(el.bbox, d.bbox)
                if iou > best_iou:
                    best, best_iou = i, iou
            if best is not None:
                used.add(best)
                el.bbox = [round(v, 1) for v in detections[best].bbox]
                snapped += 1
    return snapped


class HybridEngine:
    name = "hybrid"
    uses_llm = True

    def __init__(self, yolo: YoloEngine, claude: ClaudeVisionEngine, gates: Gates):
        self.yolo = yolo
        self.claude = claude
        self.gates = gates

    def available(self) -> bool:
        return self.yolo.available() and self.claude.available()

    def unavailable_reason(self) -> Optional[str]:
        return self.yolo.unavailable_reason() or self.claude.unavailable_reason()

    def parse(self, image: Image.Image, platform: Optional[str]) -> Program:
        warnings: List[str] = []
        detections: List[Detection] = []
        try:
            with self.gates.cpu.slot():
                detections = self.yolo.detect(image)
        except ApiError as exc:
            if exc.code == "E_BUSY":
                raise
            warnings.append("The symbol detector is unavailable; Claude read the image without detector hints.")
        except Exception as exc:  # detector crash: carry on with Claude alone
            log.error("YOLO detection failed in hybrid mode: %s", type(exc).__name__)
            warnings.append("The symbol detector failed; Claude read the image without detector hints.")
        try:
            program = self.claude.transcribe(image, platform, hints=detections)
        except ApiError as exc:
            if exc.status not in (502, 503, 504) or not detections:
                raise
            log.warning("Claude vision failed in hybrid mode (%s); falling back to YOLO + OCR", exc.code)
            with self.gates.cpu.slot():
                return self.yolo.build_program(image, detections, platform, warnings + [
                    f"Claude vision failed ({exc.code}); this result comes from the YOLO detector and OCR only."])
        snap_boxes(program, detections)
        program.engine.name = "hybrid"
        program.engine.model = f"{self.yolo.loader.model_name}+{self.claude.settings.vision_model}"
        program.detections = [d.to_out() for d in detections[:5000]]
        program.warnings = (warnings + program.warnings)[:200]
        return program
