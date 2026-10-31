"""Train-side tools: weight pinning, ONNX contract verification, backend-identical decoding."""
import hashlib
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ML_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ML_DIR / "train"))

import onnx_infer  # noqa: E402
import train as train_mod  # noqa: E402


def test_unpinned_or_tampered_weights_are_refused(tmp_path):
    fake = tmp_path / "yolov8n.pt"
    fake.write_bytes(b"not the real checkpoint")
    with pytest.raises(SystemExit, match="does not match the pinned"):
        train_mod.check_weights(fake, allow_unpinned=False)
    other = tmp_path / "mystery.pt"
    other.write_bytes(b"x")
    with pytest.raises(SystemExit, match="not pinned"):
        train_mod.check_weights(other, allow_unpinned=False)
    train_mod.check_weights(other, allow_unpinned=True)            # explicit opt-in for own checkpoints
    train_mod.check_weights(tmp_path / "yolov8n.yaml", allow_unpinned=False)  # yaml: nothing unpickled


def test_the_downloaded_pretrained_weights_match_the_pin():
    path = ML_DIR / "train" / "weights" / "yolov8n.pt"
    if not path.is_file():
        pytest.skip("pretrained weights not downloaded")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == train_mod.PINNED_WEIGHTS["yolov8n.pt"]


def test_training_never_flips_images():
    assert train_mod.HYP["fliplr"] == 0.0 and train_mod.HYP["flipud"] == 0.0


def _constant_model(path: Path, prediction: np.ndarray, imgsz: int = 64):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper
    const = numpy_helper.from_array(prediction.astype(np.float32), name="pred")
    zero = numpy_helper.from_array(np.zeros((1,), np.float32), name="zero")
    nodes = [helper.make_node("ReduceMean", ["images"], ["m"], keepdims=0),
             helper.make_node("Mul", ["m", "zero"], ["z"]),
             helper.make_node("Add", ["pred", "z"], ["output0"])]
    graph = helper.make_graph(nodes, "g", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, imgsz, imgsz])],
                              [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(prediction.shape))],
                              initializer=[const, zero])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 12)])
    model.ir_version = 7
    onnx.save(model, str(path))
    return path


def test_verify_onnx_accepts_the_backend_contract(tmp_path):
    import export
    n = sum((64 // s) ** 2 for s in (8, 16, 32))
    pred = np.zeros((1, 48, n), np.float32)
    pred[0, 4 + 3, 5] = 0.9
    report = export.verify_onnx(_constant_model(tmp_path / "ok.onnx", pred), 44, 64)
    assert report["output_shape"] == [1, 48, n] and not report["has_nms"] and report["opset"] == 12


def test_verify_onnx_rejects_a_wrong_class_count(tmp_path):
    import export
    n = sum((64 // s) ** 2 for s in (8, 16, 32))
    with pytest.raises(export.ExportCheckError, match="output"):
        export.verify_onnx(_constant_model(tmp_path / "bad.onnx", np.zeros((1, 4 + 80, n), np.float32)), 44, 64)


def test_verify_onnx_survives_python_O(tmp_path):
    """The contract checks are explicit raises, so `python -O` cannot strip them."""
    import subprocess
    n = sum((64 // s) ** 2 for s in (8, 16, 32))
    bad = _constant_model(tmp_path / "bad.onnx", np.zeros((1, 4 + 80, n), np.float32))
    code = ("import sys, pathlib; sys.path.insert(0, %r); import export\n"
            "try:\n    export.verify_onnx(pathlib.Path(%r), 44, 64)\nexcept export.ExportCheckError:\n    print('REJECTED')\n"
            % (str(ML_DIR / "train"), str(bad)))
    out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True, timeout=120)
    assert "REJECTED" in out.stdout, out.stderr


def test_local_decoder_matches_the_backend_decoder():
    letterbox, decode, impl = onnx_infer.backend_functions()
    if impl != "backend":
        pytest.skip("backend not importable")
    rng = np.random.default_rng(0)
    for k in range(5):
        img = Image.fromarray(rng.integers(0, 255, (rng.integers(80, 400), rng.integers(80, 600), 3), dtype=np.uint8))
        a1, r1, p1 = letterbox(img, (128, 128))
        a2, r2, p2 = onnx_infer._local_letterbox(img, (128, 128))
        assert np.array_equal(a1, a2) and r1 == r2 and tuple(p1) == tuple(p2)
        out = rng.random((1, 48, 336), dtype=np.float32)
        out[0, :4] *= 128
        d1 = decode(out, 0.5, 0.45, r1, p1, img.size, 44)
        d2 = onnx_infer._local_decode(out, 0.5, 0.45, r1, p1, img.size, 44)
        assert [(c, round(p, 5), tuple(round(v, 3) for v in b)) for c, p, b in d1] == \
               [(c, round(p, 5), tuple(round(v, 3) for v in b)) for c, p, b in d2]


def test_onnx_detector_runs_on_a_constant_model(tmp_path):
    n = sum((64 // s) ** 2 for s in (8, 16, 32))
    pred = np.zeros((1, 48, n), np.float32)
    pred[0, :4, 7] = [32, 32, 10, 12]
    pred[0, 4 + 1, 7] = 0.8
    det = onnx_infer.OnnxDetector(_constant_model(tmp_path / "c.onnx", pred), threads=1)
    dets = det(Image.new("RGB", (64, 64), "white"))
    assert len(dets) == 1 and dets[0][0] == 1 and abs(dets[0][1] - 0.8) < 1e-6


def test_export_refuses_checkpoints_from_outside_runs(tmp_path):
    import export
    outside = tmp_path / "best.pt"
    outside.write_bytes(b"pickle")
    with pytest.raises(SystemExit, match="not under"):
        export.check_checkpoint(outside, allow_external=False)
    export.check_checkpoint(outside, allow_external=True)
    with pytest.raises(SystemExit, match="not found"):
        export.check_checkpoint(tmp_path / "missing.pt", allow_external=True)


def test_verify_onnx_rejects_custom_operator_domains(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    import export
    node = helper.make_node("Evil", ["images"], ["output0"], domain="com.attacker")
    graph = helper.make_graph([node], "g", [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 64, 64])],
                              [helper.make_tensor_value_info("output0", TensorProto.FLOAT, [1, 48, 84])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 12), helper.make_opsetid("com.attacker", 1)])
    model.ir_version = 7
    path = tmp_path / "custom.onnx"
    onnx.save(model, str(path))
    with pytest.raises(export.ExportCheckError, match="non-standard"):
        export.verify_onnx(path, 44, 64)
