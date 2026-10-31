"""Shared engine types: the detector class table, detections and the engine protocol."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from PIL import Image

from ..schemas import DetectionOut, Program

_CLASSES_PATH = Path(__file__).resolve().parent.parent / "vendor" / "classes.json"


@dataclass(frozen=True)
class ClassInfo:
    id: int
    name: str
    mnemonic: Optional[str]
    structural: Optional[str]


def _load_classes() -> List[ClassInfo]:
    data = json.loads(_CLASSES_PATH.read_text(encoding="utf-8"))
    classes = [ClassInfo(c["id"], c["name"], c["mnemonic"], c["structural"]) for c in data["classes"]]
    if [c.id for c in classes] != list(range(data["nc"])):  # pragma: no cover - guarded by drift test
        raise RuntimeError("classes.json ids must be 0..nc-1")
    return classes


CLASSES: List[ClassInfo] = _load_classes()
CLASS_BY_ID: Dict[int, ClassInfo] = {c.id: c for c in CLASSES}
NC = len(CLASSES)


@dataclass
class Detection:
    class_id: int
    confidence: float  # 0-1
    bbox: Tuple[float, float, float, float]  # x1, y1, x2, y2 in source-image pixels

    @property
    def info(self) -> ClassInfo:
        return CLASS_BY_ID[self.class_id]

    @property
    def name(self) -> str:
        return self.info.name

    @property
    def mnemonic(self) -> Optional[str]:
        return self.info.mnemonic

    @property
    def structural(self) -> Optional[str]:
        return self.info.structural

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2

    @property
    def w(self) -> float:
        return max(1e-6, self.bbox[2] - self.bbox[0])

    @property
    def h(self) -> float:
        return max(1e-6, self.bbox[3] - self.bbox[1])

    def to_out(self) -> DetectionOut:
        return DetectionOut(class_id=self.class_id, class_name=self.name,
                            confidence=round(min(1.0, max(0.0, self.confidence)), 4),
                            bbox=[round(v, 1) for v in self.bbox])


class Engine(Protocol):
    """An image -> program engine. ``parse`` runs in a worker thread, never on the event loop."""

    name: str  # contract engine name

    def available(self) -> bool: ...

    def unavailable_reason(self) -> Optional[str]: ...

    def parse(self, image: Image.Image, platform: Optional[str]) -> Program: ...

    @property
    def uses_llm(self) -> bool: ...
