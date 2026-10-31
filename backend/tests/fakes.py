"""Test doubles for the LLM client and the YOLO detector (no network, no model file)."""
from __future__ import annotations

import json
from typing import Callable, List, Optional, Sequence, Union

from app.llm import LLMResult, UpstreamError

Reply = Union[str, Exception, Callable[[dict], str]]


class FakeLLM:
    """Returns scripted replies in order and records every call (model, system, messages)."""

    def __init__(self, replies: Sequence[Reply], stop_reason: str = "end_turn"):
        self.replies = list(replies)
        self.calls: List[dict] = []
        self.stop_reason = stop_reason

    def complete(self, *, model, system, messages, max_tokens, timeout) -> LLMResult:
        call = {"model": model, "system": system, "messages": messages, "max_tokens": max_tokens, "timeout": timeout}
        self.calls.append(call)
        if not self.replies:
            raise AssertionError("FakeLLM ran out of scripted replies")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        text = reply(call) if callable(reply) else reply
        return LLMResult(text=text, model=model, stop_reason=self.stop_reason, input_tokens=10, output_tokens=20)

    def user_text(self, call_index: int = -1) -> str:
        """All text blocks the user sent in a call, joined (images skipped)."""
        out = []
        for msg in self.calls[call_index]["messages"]:
            content = msg["content"]
            if isinstance(content, str):
                out.append(content)
            else:
                out.extend(b.get("text", "") for b in content if b.get("type") == "text")
        return "\n".join(out)


def vision_json(rungs, platform="rockwell_slc", warnings=(), **extra) -> str:
    return json.dumps({"platform": platform, "platform_confidence": 80, "rungs": rungs, "warnings": list(warnings),
                       **extra})


def upstream(kind: str) -> UpstreamError:
    return UpstreamError(kind, f"simulated {kind}")


class FakeDetector:
    model_name = "fake-yolo.onnx"

    def __init__(self, detections=None, error: Optional[Exception] = None):
        self.detections = list(detections or [])
        self.error = error
        self.calls = 0

    def detect(self, image):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.detections)
