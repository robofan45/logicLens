"""Vision engines (image -> LogicLens program) and their selection.

LOGICLENS_ENGINE = auto | yolo | claude | hybrid | stub. ``auto`` picks hybrid when a YOLO model
and an Anthropic key are both configured, else whichever one is; ``stub`` is never picked
automatically. With nothing configured, parse requests get 503 E_ENGINE_UNAVAILABLE.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

from ..errors import ApiError
from ..gate import Gates
from .claude_vision import ClaudeVisionEngine
from .hybrid import HybridEngine
from .ocr import Ocr, TesseractOcr
from .stub import StubEngine
from .yolo_onnx import DetectorLoader, YoloEngine

log = logging.getLogger("logiclens.engines")

__all__ = ["EngineRegistry"]


class EngineRegistry:
    def __init__(self, settings, gates: Gates, *, llm_client=None, detector_factory=None,
                 ocr: Optional[Ocr] = None):
        self.settings = settings
        if ocr is None and settings.ocr:
            tess = TesseractOcr(settings.tesseract_cmd, settings.ocr_timeout_s, passes=settings.ocr_passes)
            ocr = tess if tess.available() else None
            if ocr is None:
                log.warning("tesseract not found (%s): YOLO operands will be '?'", settings.tesseract_cmd)
        self.ocr = ocr
        self.loader = DetectorLoader(settings, detector_factory)
        self.stub = StubEngine()
        self.yolo = YoloEngine(self.loader, ocr, gates)
        self.claude = ClaudeVisionEngine(settings, llm_client, gates) if llm_client is not None else None
        self.hybrid = HybridEngine(self.yolo, self.claude, gates) if self.claude is not None else None

    def availability(self) -> Dict[str, bool]:
        yolo = self.yolo.available()
        claude = self.claude is not None
        return {"yolo-onnx": yolo, "claude-vision": claude, "hybrid": yolo and claude,
                "stub": self.settings.engine == "stub"}

    def _unavailable(self, why: str) -> ApiError:
        return ApiError(503, "E_ENGINE_UNAVAILABLE", why)

    def select(self):
        choice = self.settings.engine
        yolo_ok, claude_ok = self.yolo.available(), self.claude is not None
        yolo_hint = (f"{self.yolo.unavailable_reason()}; set LOGICLENS_YOLO_ONNX to a YOLOv8 .onnx model exported "
                     "with contract/classes.json")
        claude_hint = "set ANTHROPIC_API_KEY to enable Claude vision"
        if choice == "stub":
            return self.stub
        if choice == "yolo":
            if yolo_ok:
                return self.yolo
            raise self._unavailable(f"LOGICLENS_ENGINE=yolo but the YOLO engine is unavailable: {yolo_hint}.")
        if choice == "claude":
            if claude_ok:
                return self.claude
            raise self._unavailable(f"LOGICLENS_ENGINE=claude but no Anthropic key is configured: {claude_hint}.")
        if choice == "hybrid":
            if yolo_ok and claude_ok:
                return self.hybrid
            missing = [h for ok, h in ((yolo_ok, yolo_hint), (claude_ok, claude_hint)) if not ok]
            raise self._unavailable("LOGICLENS_ENGINE=hybrid needs both engines: " + "; ".join(missing) + ".")
        if yolo_ok and claude_ok:
            return self.hybrid
        if yolo_ok:
            return self.yolo
        if claude_ok:
            return self.claude
        raise self._unavailable("No vision engine is configured: set LOGICLENS_YOLO_ONNX (YOLOv8 ONNX model) "
                                "and/or ANTHROPIC_API_KEY (Claude vision).")

    def active_name(self) -> Optional[str]:
        try:
            return self.select().name
        except ApiError:
            return None

    def warmup(self) -> None:
        """Load the ONNX session at start-up so the first request is not slow."""
        if self.settings.engine in ("auto", "yolo", "hybrid") and self.loader.available():
            try:
                self.loader.get()
            except ApiError:
                pass
