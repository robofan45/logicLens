"""Deterministic stub engine: a fixed program, for tests, demos and load tests.

Active only when LOGICLENS_ENGINE=stub is set explicitly; ``auto`` never picks it, so a
misconfigured production server cannot silently return fake results."""
from __future__ import annotations

from typing import Optional

from PIL import Image

from .. import __version__
from ..program import RungDraft, finalize_rungs
from ..schemas import EngineInfo, Program

FIXED_PROGRAM = [
    "XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);",
    "[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);",
    "XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);",
]


class StubEngine:
    name = "stub"
    uses_llm = False

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> Optional[str]:
        return None

    def parse(self, image: Image.Image, platform: Optional[str]) -> Program:
        warnings = ["Stub engine: this is a fixed demo program, not read from your image."]
        rungs = finalize_rungs([RungDraft(text=t, number=i, confidence=100.0) for i, t in enumerate(FIXED_PROGRAM)],
                               warnings)
        return Program(source="image", platform=platform or "rockwell_slc",
                       platform_confidence=100.0 if platform else 90.0, rungs=rungs, detections=[],
                       warnings=warnings, engine=EngineInfo(name="stub", version=__version__, model="fixed-demo"),
                       timing_ms={"inference": 0.0})
