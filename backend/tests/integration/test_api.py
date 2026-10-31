"""HTTP-level tests against create_app(): every endpoint, every error code, headers, CORS, auth,
rate limits and the zero-retention behaviour. LLM calls use FakeLLM; YOLO uses a real onnxruntime
session on a generated model where noted."""
import io
import json
import logging
import struct
import threading
import zlib

import jsonschema
import numpy as np
import pytest
from PIL import Image

from app.engines.base import CLASSES, NC
from app.engines.ocr import FakeOcr
from tests.fakes import FakeDetector, FakeLLM, vision_json
from tests.helpers import SAMPLE_IMAGE, SAMPLE_TRUTH, encode, png_bytes

KEY = "test-key-" + "x" * 24
ID = {c.name: c.id for c in CLASSES}
PROGRAM = "XIC(Start)[XIC(Motor),XIC(Remote)]XIO(Stop)OTE(Motor);\nXIC(Motor)OTE(Lamp);"


def explain_reply():
    return json.dumps({"summary": "Seal-in motor circuit.",
                       "rung_explanations": [{"rung": 0, "text": "Seal-in."}, {"rung": 1, "text": "Lamp."}],
                       "ai_findings": []})


def upload(client, data=None, platform=None, filename="ladder.png", headers=None):
    files = {"file": (filename, data if data is not None else png_bytes(), "image/png")}
    form = {"platform": platform} if platform is not None else None
    return client.post("/api/analyze/parse", files=files, data=form, headers=headers or {})


def assert_error(resp, status, code):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == resp.headers["x-request-id"]
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert "Traceback" not in resp.text and 'File "' not in resp.text
    assert_security_headers(resp)
    return body["error"]


def assert_security_headers(resp):
    h = resp.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY"
    assert h["content-security-policy"].startswith("default-src 'none'")
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert h["x-request-id"]


# ============================================================================ health / meta
def test_health_is_open_and_says_when_the_api_is_open(make_client):
    resp = make_client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok" and body["auth"] == "open" and body["warnings"]
    assert_security_headers(resp)


def test_health_answers_head_for_load_balancers(make_client):
    resp = make_client().head("/health")
    assert resp.status_code == 200 and resp.content == b""


def test_health_stays_open_when_keys_are_configured(make_client):
    body = make_client(api_keys=KEY).get("/health").json()
    assert body["auth"] == "api_key" and "warnings" not in body


def test_meta_reports_capabilities_and_no_secrets(make_client):
    client = make_client(engine="stub", api_keys=KEY, anthropic_api_key="sk-ant-SECRET-123", llm=FakeLLM([]),
                         redis_url="redis://:hunter2@localhost:1/0")
    resp = client.get("/api/meta", headers={"X-API-Key": KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["engines"]["active"] == "stub"
    assert body["llm"]["enabled"] is True and body["llm"]["models"]["vision"] == "claude-sonnet-5-5"
    assert body["limits"]["upload_mb"] == 8 and body["classes"]["count"] == NC == 44
    assert "rockwell_slc" in body["platforms"]
    for secret in ("sk-ant-SECRET-123", KEY, "hunter2"):
        assert secret not in resp.text


# ============================================================================ parse
def test_parse_with_the_stub_engine_matches_the_schema(make_client, program_schema):
    resp = upload(make_client(engine="stub"), platform="rockwell_slc")
    assert resp.status_code == 200, resp.text
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert program["engine"]["name"] == "stub" and program["platform"] == "rockwell_slc"
    assert program["image"]["width"] == 64 and program["image"]["height"] == 48
    assert set(program["image"]["quality"]) == {"overall", "blur", "contrast"}
    assert {"decode", "total"} <= set(program["timing_ms"])
    assert_security_headers(resp)


def test_parse_the_real_sample_through_the_decode_path(make_client, program_schema):
    data = SAMPLE_IMAGE.read_bytes()
    resp = make_client(engine="stub").post("/api/analyze/parse",
                                           files={"file": ("PLC1.webp", data, "image/webp")})
    assert resp.status_code == 200
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert (program["image"]["width"], program["image"]["height"]) == (892, 508)
    assert program["image"]["quality"]["overall"] >= 80


def test_parse_oversize_upload_streamed_without_content_length_is_413(make_client):
    client = make_client(engine="stub", max_upload_mb=0.05)
    boundary = "b0undary"
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200_000

    def body():
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.png"\r\n\r\n'.encode()
        for i in range(0, len(payload), 8192):
            yield payload[i:i + 8192]
        yield f"\r\n--{boundary}--\r\n".encode()

    resp = client.post("/api/analyze/parse", content=body(),
                       headers={"content-type": f"multipart/form-data; boundary={boundary}"})
    assert_error(resp, 413, "E_TOO_LARGE")


def test_parse_declared_content_length_over_the_cap_is_rejected_early(make_client):
    client = make_client(engine="stub", max_upload_mb=0.05)
    resp = upload(client, data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100_000)
    assert_error(resp, 413, "E_TOO_LARGE")


@pytest.mark.parametrize("name,data", [
    ("gif", encode(Image.new("RGB", (8, 8)), "GIF")),
    ("svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("pdf", b"%PDF-1.4\n%%EOF"),
    ("polyglot", png_bytes() + b"PK\x03\x04zip-payload"),
])
def test_parse_rejects_non_images_and_polyglots_with_415(make_client, name, data):
    assert_error(upload(make_client(engine="stub"), data=data), 415, "E_UNSUPPORTED_MEDIA")


def test_parse_truncated_image_is_422(make_client):
    data = encode(Image.effect_noise((128, 128), 50).convert("RGB"), "PNG")
    assert_error(upload(make_client(engine="stub"), data=data[: len(data) // 2]), 422, "E_BAD_IMAGE")


def test_parse_huge_dimensions_are_422(make_client):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))
    bomb = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 50_000, 50_000, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 100)) + chunk(b"IEND", b""))
    err = assert_error(upload(make_client(engine="stub"), data=bomb), 422, "E_BAD_IMAGE")
    assert "8000 px" in err["message"] and "40 MP" in err["message"]  # tells the user the limits


def test_parse_missing_file_is_422(make_client):
    resp = make_client(engine="stub").post("/api/analyze/parse", data={"platform": "unknown"},
                                           files={"other": ("a.txt", b"x", "text/plain")})
    err = assert_error(resp, 422, "E_VALIDATION")
    assert err["details"][0]["loc"] == ["file"]


def test_parse_unknown_platform_is_422_without_echoing_it(make_client):
    evil = "<script>alert(1)</script>"
    err = assert_error(upload(make_client(engine="stub"), platform=evil), 422, "E_VALIDATION")
    assert evil not in json.dumps(err)


def test_parse_with_a_json_body_is_415(make_client):
    resp = make_client(engine="stub").post("/api/analyze/parse", json={"file": "x"})
    assert_error(resp, 415, "E_UNSUPPORTED_MEDIA")


def test_parse_without_any_engine_is_503_with_an_actionable_message(make_client):
    err = assert_error(upload(make_client()), 503, "E_ENGINE_UNAVAILABLE")
    assert "ANTHROPIC_API_KEY" in err["message"] and "LOGICLENS_YOLO_ONNX" in err["message"]


def test_parse_is_503_busy_when_the_inference_gate_is_full(make_client):
    client = make_client(engine="stub", inference_concurrency=1, inference_queue=0)
    gate = client.app.state.gates.cpu
    holding, release = threading.Event(), threading.Event()

    def hold():
        with gate.slot():
            holding.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    holding.wait(5)
    try:
        resp = upload(client)
    finally:
        release.set()
        t.join()
    assert_error(resp, 503, "E_BUSY")
    assert resp.headers["retry-after"]
    assert upload(client).status_code == 200


def test_parse_with_claude_engine_uses_the_llm_budget(make_client, program_schema):
    reply = vision_json([{"number": i, "text": t} for i, t in enumerate(SAMPLE_TRUTH)])
    client = make_client(engine="claude", anthropic_api_key="sk-test", llm=FakeLLM([reply]), llm_rate_limit_per_min=1)
    resp = upload(client)
    assert resp.status_code == 200, resp.text
    jsonschema.validate(resp.json(), program_schema)
    assert resp.json()["engine"]["name"] == "claude-vision"
    assert_error(upload(client), 429, "E_RATE_LIMITED")


def test_parse_with_claude_returning_garbage_twice_is_502(make_client):
    client = make_client(engine="claude", anthropic_api_key="sk-test", llm=FakeLLM(["nope", "still nope"]))
    assert_error(upload(client), 502, "E_ENGINE_FAILED")


# ---------------------------------------------------------------- YOLO through a real onnxruntime session
def _constant_yolo_model(tmp_path, boxes):
    """boxes: (class_name, cx, cy, w, h, score) in 640x640 letterbox pixels."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    pred = np.zeros((1, 4 + NC, 32), np.float32)
    for i, (name, cx, cy, w, h, score) in enumerate(boxes):
        pred[0, :4, i] = (cx, cy, w, h)
        pred[0, 4 + ID[name], i] = score
    nodes = [helper.make_node("Constant", [], ["p"], value=numpy_helper.from_array(pred)),
             helper.make_node("ReduceMean", ["images"], ["m"], keepdims=0),
             helper.make_node("Constant", [], ["z"], value=numpy_helper.from_array(np.array(0, np.float32))),
             helper.make_node("Mul", ["m", "z"], ["mz"]), helper.make_node("Add", ["p", "mz"], ["output0"])]
    graph = helper.make_graph(nodes, "g", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 640, 640])],
                              [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 4 + NC, 32])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    path = tmp_path / "tiny-yolo.onnx"
    onnx.save(model, str(path))
    return path


# 640x320 white image -> letterbox ratio 1.0, pad (0, 160): source y = letterbox y - 160
YOLO_BOXES = [("NO_Contact", 112, 260, 24, 18, 0.9), ("NC_Contact", 212, 260, 24, 18, 0.9),
              ("Output_Coil", 560, 260, 28, 18, 0.9)]
YOLO_LABELS = [("Start", (112, 86)), ("Stop", (212, 86)), ("Motor", (560, 86))]


def _white(w=640, h=320):
    return encode(Image.new("RGB", (w, h), "white"), "PNG")


def test_parse_with_yolo_runs_onnxruntime_and_the_assembler(make_client, tmp_path, program_schema):
    model = _constant_yolo_model(tmp_path, YOLO_BOXES)
    client = make_client(engine="yolo", yolo_onnx=model, ocr=FakeOcr(YOLO_LABELS))
    resp = upload(client, data=_white())
    assert resp.status_code == 200, resp.text
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert [r["text"] for r in program["rungs"]] == ["XIC(Start)XIO(Stop)OTE(Motor);"]
    assert program["engine"]["model"] == "tiny-yolo.onnx"
    assert [d["class_name"] for d in program["detections"]] == ["NO_Contact", "NC_Contact", "Output_Coil"]
    assert {"decode", "inference", "assemble", "total"} <= set(program["timing_ms"])


def test_parse_with_hybrid_snaps_claude_elements_to_yolo_boxes(make_client, tmp_path, program_schema):
    model = _constant_yolo_model(tmp_path, YOLO_BOXES)
    reply = vision_json([{"number": 0, "text": "XIC(Start)XIO(Stop)OTE(Motor);",
                          "elements": [{"mnemonic": "XIC", "bbox": [98, 90, 128, 112]},
                                       {"mnemonic": "XIO", "bbox": [198, 90, 228, 112]},
                                       {"mnemonic": "OTE", "bbox": [540, 90, 580, 112]}]}])
    client = make_client(yolo_onnx=model, anthropic_api_key="sk-test", llm=FakeLLM([reply]),
                         ocr=FakeOcr(YOLO_LABELS))
    resp = upload(client, data=_white())
    assert resp.status_code == 200, resp.text
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert program["engine"]["name"] == "hybrid"
    assert program["rungs"][0]["elements"][0]["bbox"] == [100.0, 91.0, 124.0, 109.0]


def test_parse_engine_with_a_broken_model_file_is_503(make_client, tmp_path):
    bad = tmp_path / "broken.onnx"
    bad.write_bytes(b"not a model")
    client = make_client(engine="yolo", yolo_onnx=bad)
    err = assert_error(upload(client), 503, "E_ENGINE_UNAVAILABLE")
    assert "broken.onnx" in err["message"] and str(tmp_path) not in err["message"]


# ============================================================================ text
def test_text_happy_path(make_client, program_schema):
    resp = make_client().post("/api/analyze/text", json={"text": "\n".join(SAMPLE_TRUTH)})
    assert resp.status_code == 200
    program = resp.json()
    jsonschema.validate(program, program_schema)
    assert program["source"] == "text" and program["engine"]["name"] == "text"
    assert [r["text"] for r in program["rungs"]] == SAMPLE_TRUTH
    assert program["platform"] == "rockwell_slc"


def test_text_syntax_error_is_422_with_parser_details(make_client):
    from app.vendor.logiclens_ladder import parse_program

    text = "XIC(A)OTE(B);\nXIC(A]OTE(B);\nXIC(A)FOO(B);"
    resp = make_client().post("/api/analyze/text", json={"text": text})
    err = assert_error(resp, 422, "E_LADDER_SYNTAX")
    assert err["details"] == [e.to_dict() for e in parse_program(text).errors]
    assert [(d["code"], d["line"]) for d in err["details"]] == [("E_UNBALANCED", 2), ("E_UNKNOWN_MNEMONIC", 3)]


@pytest.mark.parametrize("body,status,code", [
    ({"text": ""}, 422, "E_LADDER_SYNTAX"),
    ({}, 422, "E_VALIDATION"),
    ({"text": "XIC(A)OTE(B);", "platform": "plc5000"}, 422, "E_VALIDATION"),
    ({"text": 42}, 422, "E_VALIDATION"),
])
def test_text_validation_errors(make_client, body, status, code):
    assert_error(make_client().post("/api/analyze/text", json=body), status, code)


def test_text_body_over_the_json_cap_is_413(make_client):
    big = {"text": "XIC(A)OTE(B);\n" * 30_000}
    assert_error(make_client(max_json_kb=64).post("/api/analyze/text", json=big), 413, "E_TOO_LARGE")


def test_text_wrong_content_type_is_415_and_malformed_json_is_400(make_client):
    client = make_client()
    assert_error(client.post("/api/analyze/text", content=b"text=1", headers={"content-type": "text/plain"}),
                 415, "E_UNSUPPORTED_MEDIA")
    assert_error(client.post("/api/analyze/text", content=b'{"text": ', headers={"content-type": "application/json"}),
                 400, "E_BAD_REQUEST")


def test_text_program_over_the_parser_limit_is_the_parsers_e_limit(make_client):
    text = "XIC(A)OTE(B);\n" * 15_000  # 210 000 chars > 200 000
    resp = make_client(max_json_kb=1024).post("/api/analyze/text", json={"text": text})
    err = assert_error(resp, 422, "E_LADDER_SYNTAX")
    assert [d["code"] for d in err["details"]] == ["E_LIMIT"]


# ============================================================================ explain / chat
def test_explain_and_chat_are_503_without_an_llm(make_client):
    client = make_client()
    assert_error(client.post("/api/analyze/explain", json={"program_text": PROGRAM}), 503, "E_LLM_DISABLED")
    assert_error(client.post("/api/chat", json={"program_text": PROGRAM, "question": "q"}), 503, "E_LLM_DISABLED")


def test_explain_happy_path(make_client):
    fake = FakeLLM([explain_reply()])
    client = make_client(anthropic_api_key="sk-test", llm=fake)
    resp = client.post("/api/analyze/explain", json={"program_text": PROGRAM, "platform": "rockwell_logix",
                                                     "user_context": "conveyor", "findings": [{"title": "x"}]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"summary", "rung_explanations", "ai_findings", "model", "disclaimer"}
    assert body["model"] == "claude-sonnet-5-5" and "advisory" in body["disclaimer"]
    assert_security_headers(resp)


def test_chat_happy_path(make_client):
    client = make_client(anthropic_api_key="sk-test", llm=FakeLLM(["Rung 1 lights the lamp."]))
    resp = client.post("/api/chat", json={"program_text": PROGRAM, "question": "What does rung 1 do?",
                                          "history": [{"role": "user", "content": "hi"},
                                                      {"role": "assistant", "content": "hello"}]})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Rung 1 lights the lamp."


def test_explain_errors(make_client):
    client = make_client(anthropic_api_key="sk-test", llm=FakeLLM(["not json", "still not json"]))
    assert_error(client.post("/api/analyze/explain", json={"program_text": "XIC(A]"}), 422, "E_LADDER_SYNTAX")
    assert_error(client.post("/api/analyze/explain", json={"program_text": "x" * 300_000}), 413, "E_TOO_LARGE")
    assert_error(client.post("/api/analyze/explain", json={"program_text": PROGRAM}), 502, "E_LLM_FAILED")
    assert_error(client.post("/api/chat", json={"program_text": PROGRAM}), 422, "E_VALIDATION")


def test_llm_budget_is_stricter_than_the_api_budget(make_client):
    client = make_client(anthropic_api_key="sk-test", llm=FakeLLM(["a", "b", "c"]), llm_rate_limit_per_min=2,
                         rate_limit_per_min=100)
    for _ in range(2):
        assert client.post("/api/chat", json={"program_text": PROGRAM, "question": "q"}).status_code == 200
    resp = client.post("/api/chat", json={"program_text": PROGRAM, "question": "q"})
    assert_error(resp, 429, "E_RATE_LIMITED")
    assert resp.headers["x-ratelimit-limit"] == "2"
    assert client.post("/api/analyze/text", json={"text": PROGRAM}).status_code == 200


# ============================================================================ auth
def test_api_keys_are_required_on_api_routes(make_client):
    client = make_client(api_keys=KEY)
    err = assert_error(client.post("/api/analyze/text", json={"text": PROGRAM}), 401, "E_UNAUTHORIZED")
    assert "X-API-Key" in err["message"]
    resp = client.post("/api/analyze/text", json={"text": PROGRAM}, headers={"X-API-Key": "wrong" * 8})
    assert_error(resp, 401, "E_UNAUTHORIZED")
    assert resp.headers["www-authenticate"].startswith("ApiKey")
    assert client.post("/api/analyze/text", json={"text": PROGRAM}, headers={"X-API-Key": KEY}).status_code == 200
    assert_error(client.get("/api/meta"), 401, "E_UNAUTHORIZED")


# ============================================================================ rate limit
def test_rate_limit_429_end_to_end(make_client):
    client = make_client(rate_limit_per_min=3)
    statuses, last = [], None
    for _ in range(4):
        last = client.post("/api/analyze/text", json={"text": PROGRAM})
        statuses.append(last.status_code)
    assert statuses == [200, 200, 200, 429]
    assert_error(last, 429, "E_RATE_LIMITED")
    assert int(last.headers["retry-after"]) >= 1
    assert last.headers["x-ratelimit-remaining"] == "0"
    assert client.get("/health").status_code == 200  # never rate limited


def test_successful_responses_carry_rate_limit_headers(make_client):
    resp = make_client(rate_limit_per_min=10).post("/api/analyze/text", json={"text": PROGRAM})
    assert resp.headers["x-ratelimit-limit"] == "10" and resp.headers["x-ratelimit-remaining"] == "9"


# ============================================================================ CORS
def test_cors_preflight_for_an_allowed_origin(make_client):
    resp = make_client(api_keys=KEY).options("/api/analyze/parse", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-api-key"})
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "x-api-key" in resp.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in resp.headers


def test_cors_preflight_for_a_disallowed_origin_is_rejected(make_client):
    resp = make_client().options("/api/analyze/parse", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert_error(resp, 400, "E_CORS_REJECTED")
    assert "access-control-allow-origin" not in resp.headers


def test_cors_simple_request_only_reflects_allowed_origins(make_client):
    client = make_client(cors_origins="https://app.logiclens.example")
    ok = client.get("/health", headers={"Origin": "https://app.logiclens.example"})
    assert ok.headers["access-control-allow-origin"] == "https://app.logiclens.example"
    assert "x-request-id" in ok.headers["access-control-expose-headers"].lower()
    bad = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


# ============================================================================ errors and headers
def test_unknown_route_and_wrong_method_use_the_envelope(make_client):
    client = make_client()
    assert_error(client.get("/nope"), 404, "E_NOT_FOUND")
    assert_error(client.get("/api/analyze/text"), 405, "E_METHOD_NOT_ALLOWED")


def test_unhandled_exception_is_a_500_envelope_without_a_traceback(make_client, caplog):
    client = make_client()

    @client.app.get("/boom")
    async def boom():
        raise RuntimeError("secret internal detail")

    with caplog.at_level(logging.ERROR, logger="logiclens"):
        resp = client.get("/boom")
    err = assert_error(resp, 500, "E_INTERNAL")
    assert "secret internal detail" not in resp.text
    assert any(err["request_id"] in r.getMessage() for r in caplog.records)


def test_request_id_is_echoed_when_safe_and_replaced_otherwise(make_client):
    client = make_client()
    assert client.get("/health", headers={"X-Request-ID": "trace-12345678"}).headers["x-request-id"] == "trace-12345678"
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\r\nX-Injected: 1"}).headers["x-request-id"]
    assert replaced != "bad id" and len(replaced) == 32


def test_docs_are_off_by_default_and_on_with_a_relaxed_csp(make_client):
    assert make_client().get("/docs").status_code == 404
    client = make_client(docs=True)
    resp = client.get("/docs")
    assert resp.status_code == 200 and "cdn.jsdelivr.net" in resp.headers["content-security-policy"]
    assert client.get("/openapi.json").status_code == 200


# ============================================================================ zero retention
def test_uploads_never_touch_the_filesystem_and_never_reach_the_logs(make_client, monkeypatch, caplog):
    import tempfile

    def no_disk(*args, **kwargs):
        raise AssertionError("upload spooled to disk")

    for name in ("SpooledTemporaryFile", "NamedTemporaryFile", "TemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_disk)
    client = make_client(engine="stub")
    with caplog.at_level(logging.DEBUG):
        resp = upload(client, data=png_bytes(400, 300), filename="secret-plant-layout.png")
    assert resp.status_code == 200
    assert not any("secret-plant-layout" in r.getMessage() for r in caplog.records)


# ============================================================================ concurrency
def test_cpu_work_does_not_block_the_event_loop(make_client, monkeypatch):
    import time

    client = make_client(engine="stub", inference_concurrency=2)
    stub = client.app.state.engines.stub
    real_parse = stub.parse

    def slow_parse(image, platform):
        time.sleep(1.0)  # stands in for YOLO + OCR
        return real_parse(image, platform)

    monkeypatch.setattr(stub, "parse", slow_parse)
    result = {}
    worker = threading.Thread(target=lambda: result.setdefault("parse", upload(client)))
    worker.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert client.get("/health").status_code == 200
    elapsed = time.monotonic() - started
    worker.join()
    assert result["parse"].status_code == 200
    assert elapsed < 0.5, f"/health waited {elapsed:.2f}s behind a parse: the event loop was blocked"


def test_module_level_app_for_uvicorn_builds_from_the_environment():
    from fastapi import FastAPI

    import app.main as main

    assert isinstance(main.app, FastAPI)
