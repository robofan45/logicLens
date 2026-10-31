import json

import jsonschema
import pytest
from PIL import Image

from app.engines import EngineRegistry
from app.engines.base import CLASSES, Detection
from app.engines.ocr import FakeOcr
from app.errors import ApiError
from app.gate import Gates
from app.settings import Settings
from tests.fakes import FakeDetector, FakeLLM, upstream, vision_json
from tests.helpers import REPO, SAMPLE_TRUTH

ID = {c.name: c.id for c in CLASSES}
SCHEMA = REPO / "contract" / "program.schema.json"


def validate(program):
    if SCHEMA.exists():
        jsonschema.validate(program, json.loads(SCHEMA.read_text()))


def dets_simple():
    return [Detection(ID["NO_Contact"], 0.92, (100, 91, 124, 109)), Detection(ID["Output_Coil"], 0.88, (700, 91, 729, 109))]


def labels_simple():
    return [("Start", (112, 84)), ("Motor", (714, 84))]


def registry(tmp_path=None, *, engine="auto", model=True, llm_replies=None, detector=None, ocr=None):
    kwargs = {"engine": engine}
    if model and tmp_path is not None:
        path = tmp_path / "model.onnx"
        path.write_bytes(b"onnx")
        kwargs["yolo_onnx"] = path
    if llm_replies is not None:
        kwargs["anthropic_api_key"] = "sk-test"
    s = Settings(**kwargs)
    fake = FakeLLM(llm_replies) if llm_replies is not None else None
    det = detector or FakeDetector(dets_simple())
    reg = EngineRegistry(s, Gates.from_settings(s), llm_client=fake, detector_factory=lambda p: det,
                         ocr=ocr if ocr is not None else FakeOcr(labels_simple()))
    return reg, fake, det


IMG = Image.new("RGB", (800, 200), "white")


# ------------------------------------------------------------------------------ selection
def test_auto_without_anything_is_503_with_an_actionable_message():
    reg, _, _ = registry(model=False)
    with pytest.raises(ApiError) as exc:
        reg.select()
    assert (exc.value.status, exc.value.code) == (503, "E_ENGINE_UNAVAILABLE")
    assert "LOGICLENS_YOLO_ONNX" in exc.value.message and "ANTHROPIC_API_KEY" in exc.value.message
    assert reg.availability() == {"yolo-onnx": False, "claude-vision": False, "hybrid": False, "stub": False}


def test_auto_picks_hybrid_then_yolo_then_claude(tmp_path):
    assert registry(tmp_path, llm_replies=[])[0].select().name == "hybrid"
    assert registry(tmp_path)[0].select().name == "yolo-onnx"
    assert registry(model=False, llm_replies=[])[0].select().name == "claude-vision"


@pytest.mark.parametrize("choice,hint", [("yolo", "LOGICLENS_YOLO_ONNX"), ("claude", "ANTHROPIC_API_KEY"),
                                         ("hybrid", "LOGICLENS_YOLO_ONNX")])
def test_explicit_engine_that_is_not_configured_is_503(choice, hint):
    reg, _, _ = registry(engine=choice, model=False)
    with pytest.raises(ApiError) as exc:
        reg.select()
    assert exc.value.code == "E_ENGINE_UNAVAILABLE" and hint in exc.value.message


def test_stub_is_only_active_when_selected_explicitly(tmp_path):
    reg, _, _ = registry(tmp_path)
    assert reg.availability()["stub"] is False
    reg, _, _ = registry(engine="stub", model=False)
    assert reg.select().name == "stub" and reg.availability()["stub"] is True


def test_missing_model_file_is_unavailable_without_leaking_the_path(tmp_path):
    s = Settings(engine="yolo", yolo_onnx=tmp_path / "secret-dir" / "m.onnx")
    reg = EngineRegistry(s, Gates.from_settings(s))
    with pytest.raises(ApiError) as exc:
        reg.select()
    assert "secret-dir" not in exc.value.message and "m.onnx" in exc.value.message


def test_model_that_fails_to_load_is_reported_once_and_cached(tmp_path):
    calls = []

    def factory(path):
        calls.append(path)
        raise ValueError("bad model")

    path = tmp_path / "m.onnx"
    path.write_bytes(b"x")
    s = Settings(engine="yolo", yolo_onnx=path)
    reg = EngineRegistry(s, Gates.from_settings(s), detector_factory=factory, ocr=FakeOcr([]))
    reg.warmup()
    for _ in range(2):
        with pytest.raises(ApiError) as exc:
            reg.select().parse(IMG, None)
        assert exc.value.code == "E_ENGINE_UNAVAILABLE"
    assert len(calls) == 1
    assert reg.availability()["yolo-onnx"] is False


# ------------------------------------------------------------------------------ engines
def test_stub_engine_is_deterministic_and_schema_valid():
    reg, _, _ = registry(engine="stub", model=False)
    a = reg.select().parse(IMG, None).to_json()
    b = reg.select().parse(IMG, None).to_json()
    assert a == b
    assert [r["text"] for r in a["rungs"]] == SAMPLE_TRUTH
    assert a["engine"]["name"] == "stub" and a["warnings"]
    validate(a)


def test_yolo_engine_assembles_detections_into_a_program(tmp_path):
    reg, _, det = registry(tmp_path, engine="yolo")
    program = reg.select().parse(IMG, None).to_json()
    validate(program)
    assert [r["text"] for r in program["rungs"]] == ["XIC(Start)OTE(Motor);"]
    assert program["engine"] == {"name": "yolo-onnx", "version": program["engine"]["version"], "model": "model.onnx"}
    assert [d["class_name"] for d in program["detections"]] == ["NO_Contact", "Output_Coil"]
    assert {"inference", "assemble"} <= set(program["timing_ms"])
    assert det.calls == 1


def test_hybrid_uses_claude_text_with_yolo_boxes(tmp_path):
    reply = vision_json([{"number": 0, "text": "XIC(Start)OTE(Motor);",
                          "elements": [{"mnemonic": "XIC", "bbox": [98, 88, 126, 112]},
                                       {"mnemonic": "OTE", "bbox": [690, 85, 735, 115]}]}])
    reg, fake, _ = registry(tmp_path, llm_replies=[reply])
    program = reg.select().parse(IMG, None).to_json()
    validate(program)
    assert program["engine"]["name"] == "hybrid"
    assert program["rungs"][0]["text"] == "XIC(Start)OTE(Motor);"
    assert program["rungs"][0]["elements"][0]["bbox"] == [100, 91, 124, 109]     # snapped to the YOLO box
    assert program["rungs"][0]["elements"][1]["bbox"] == [700, 91, 729, 109]
    assert len(program["detections"]) == 2
    assert "<detector_hints>" in fake.user_text()


def test_hybrid_falls_back_to_yolo_when_claude_fails(tmp_path):
    reg, _, _ = registry(tmp_path, llm_replies=[upstream("timeout")])
    program = reg.select().parse(IMG, None).to_json()
    assert program["engine"]["name"] == "yolo-onnx"
    assert program["rungs"][0]["text"] == "XIC(Start)OTE(Motor);"
    assert any("Claude" in w for w in program["warnings"])


def test_hybrid_continues_with_claude_when_yolo_fails(tmp_path):
    reply = vision_json([{"number": 0, "text": "XIC(A)OTE(B);"}])
    reg, _, _ = registry(tmp_path, llm_replies=[reply], detector=FakeDetector(error=RuntimeError("onnx crashed")))
    program = reg.select().parse(IMG, None).to_json()
    assert program["engine"]["name"] == "hybrid"
    assert program["rungs"][0]["text"] == "XIC(A)OTE(B);"
    assert any("detector" in w.lower() for w in program["warnings"])


def test_engines_report_whether_they_use_the_llm(tmp_path):
    reg, _, _ = registry(tmp_path, llm_replies=[])
    assert reg.hybrid.uses_llm and reg.claude.uses_llm
    assert not reg.yolo.uses_llm and not reg.stub.uses_llm
