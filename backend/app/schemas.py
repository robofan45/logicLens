"""Pydantic models mirroring contract/program.schema.json and the explain/chat bodies (contract s.2, s.4).

Response models are strict (``extra='forbid'``) so the API cannot drift from the contract silently;
request models ignore unknown fields so a newer web client does not break an older backend.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .vendor.logiclens_ladder import LIMITS

Platform = Literal[
    "rockwell_logix", "rockwell_slc", "siemens_tia", "schneider", "mitsubishi", "omron", "abb",
    "generic_iec", "unknown",
]
PLATFORMS: List[str] = list(Platform.__args__)  # type: ignore[attr-defined]
EngineName = Literal["yolo-onnx", "claude-vision", "hybrid", "text", "stub"]
Severity = Literal["critical", "high", "medium", "low"]

BBox = List[float]


def _check_bbox(v: Optional[List[float]]) -> Optional[List[float]]:
    if v is None:
        return v
    if len(v) != 4:
        raise ValueError("bbox must have 4 numbers [x1, y1, x2, y2]")
    return [round(float(x), 1) for x in v]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------- program (s.2)
class Element(_Strict):
    index: int = Field(ge=0)
    mnemonic: str = Field(max_length=8)
    operands: List[str] = Field(default_factory=list, max_length=8)
    bbox: Optional[BBox] = None
    confidence: Optional[float] = Field(None, ge=0, le=100)

    _bbox = field_validator("bbox")(_check_bbox)


class RungOut(_Strict):
    number: int = Field(ge=0)
    comment: Optional[str] = Field(None, max_length=2000)
    text: str = Field(min_length=1, max_length=LIMITS["rung_chars"])
    confidence: Optional[float] = Field(None, ge=0, le=100)
    bbox: Optional[BBox] = None
    elements: List[Element] = Field(default_factory=list, max_length=256)

    _bbox = field_validator("bbox")(_check_bbox)


class DetectionOut(_Strict):
    class_id: int = Field(ge=0, le=43)
    class_name: str
    confidence: float = Field(ge=0, le=1)
    bbox: BBox

    _bbox = field_validator("bbox")(_check_bbox)


class Quality(_Strict):
    overall: float = Field(ge=0, le=100)
    blur: float = Field(ge=0, le=100)
    contrast: float = Field(ge=0, le=100)


class ImageInfo(_Strict):
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    quality: Optional[Quality] = None


class EngineInfo(_Strict):
    name: EngineName
    version: Optional[str] = None
    model: Optional[str] = None


class Program(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    source: Literal["image", "text"]
    platform: Platform = "unknown"
    platform_confidence: Optional[float] = Field(None, ge=0, le=100)
    rungs: List[RungOut] = Field(default_factory=list, max_length=LIMITS["rungs"])
    detections: Optional[List[DetectionOut]] = Field(None, max_length=5000)
    image: Optional[ImageInfo] = None
    warnings: List[str] = Field(default_factory=list, max_length=200)
    engine: EngineInfo
    timing_ms: Optional[Dict[str, float]] = None

    @field_validator("warnings", mode="before")
    @classmethod
    def _clip_warnings(cls, v):
        return [str(w)[:500] for w in (v or [])][:200]

    @field_validator("timing_ms")
    @classmethod
    def _non_negative(cls, v):
        if v is None:
            return v
        return {k: round(max(0.0, float(t)), 1) for k, t in v.items()}

    def to_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


# ---------------------------------------------------------------------------- requests
class _Request(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


class TextRequest(_Request):
    # No max_length: the JSON body cap bounds it and the contract parser reports E_LIMIT itself,
    # so the API returns the same error code as the browser's parser.
    text: str
    platform: Optional[Platform] = None


class FindingIn(_Request):
    """A rule-based finding from the browser, passed to the LLM as context only.
    The contract does not pin this shape; these are the fields the backend reads."""
    id: Optional[str] = Field(None, max_length=64)
    rule: Optional[str] = Field(None, max_length=64)
    severity: Optional[str] = Field(None, max_length=16)
    title: Optional[str] = Field(None, max_length=200)
    message: Optional[str] = Field(None, max_length=2000)
    description: Optional[str] = Field(None, max_length=2000)
    recommendation: Optional[str] = Field(None, max_length=2000)
    rungs: Optional[List[int]] = Field(None, max_length=64)


class ExplainRequest(_Request):
    program_text: str = Field(min_length=1, max_length=LIMITS["program_chars"])
    platform: Optional[Platform] = None
    user_context: Optional[str] = Field(None, max_length=4000)
    findings: Optional[List[FindingIn]] = Field(None, max_length=100)
    depth: Literal["standard", "deep"] = "standard"


class ChatTurn(_Request):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(_Request):
    program_text: str = Field(min_length=1, max_length=LIMITS["program_chars"])
    question: str = Field(min_length=1, max_length=4000)
    history: Optional[List[ChatTurn]] = Field(None, max_length=20)


# ---------------------------------------------------------------------------- explain / chat out
class RungExplanation(_Strict):
    rung: int = Field(ge=0)
    text: str = Field(max_length=4000)


class AiFinding(_Strict):
    severity: Severity
    title: str = Field(max_length=200)
    rungs: List[int] = Field(default_factory=list, max_length=64)
    description: str = Field(max_length=4000)
    recommendation: str = Field(max_length=4000)


class ExplainResponse(_Strict):
    summary: str
    rung_explanations: List[RungExplanation]
    ai_findings: List[AiFinding]
    model: str
    disclaimer: str


class ChatResponse(_Strict):
    answer: str
    model: str
    disclaimer: str
