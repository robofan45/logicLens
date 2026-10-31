import numpy as np
import pytest
from PIL import Image

from app.engines.base import NC, CLASS_BY_ID
from app.engines.yolo_onnx import YoloOnnxDetector, decode_yolov8, letterbox, nms

N_ANCHORS = 64


def _tensor(entries, n=N_ANCHORS, transposed=False):
    """entries: (anchor, cx, cy, w, h, class_id, score) in letterboxed pixels."""
    out = np.zeros((1, 4 + NC, n), dtype=np.float32)
    for a, cx, cy, w, h, cls, score in entries:
        out[0, :4, a] = (cx, cy, w, h)
        out[0, 4 + cls, a] = score
    return out.transpose(0, 2, 1).copy() if transposed else out


def test_letterbox_keeps_aspect_and_pads_with_grey():
    img = Image.new("RGB", (200, 100), (255, 0, 0))
    arr, ratio, (dw, dh) = letterbox(img, (640, 640))
    assert arr.shape == (640, 640, 3) and arr.dtype == np.uint8
    assert ratio == pytest.approx(3.2)
    assert (dw, dh) == (0.0, 160.0)
    assert tuple(arr[10, 320]) == (114, 114, 114)   # padding
    assert tuple(arr[320, 320]) == (255, 0, 0)      # content


def test_nms_suppresses_overlaps_and_keeps_disjoint_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.9, 0.8, 0.7], dtype=np.float32)
    assert nms(boxes, scores, 0.5) == [0, 2]


def test_decode_thresholds_runs_classwise_nms_and_maps_back():
    out = _tensor([
        (0, 320, 320, 100, 50, 0, 0.90),   # NO_Contact
        (1, 323, 321, 100, 50, 0, 0.80),   # duplicate of 0 -> suppressed
        (2, 320, 320, 100, 50, 4, 0.70),   # same box, other class -> kept (class-wise NMS)
        (3, 100, 100, 20, 20, 1, 0.10),    # below threshold
        (4, 500, 200, 40, 40, 42, 0.55),   # rail
    ])
    dets = decode_yolov8(out, conf_thres=0.25, iou_thres=0.45, ratio=1.0, pad=(0.0, 0.0), orig_size=(640, 640))
    assert [(d.class_id, round(d.confidence, 2)) for d in dets] == [(0, 0.9), (4, 0.7), (42, 0.55)]
    assert dets[0].bbox == pytest.approx((270, 295, 370, 345))
    assert dets[0].name == "NO_Contact" and dets[0].mnemonic == "XIC"
    assert dets[2].structural == "rail_left"


def test_decode_undoes_the_letterbox_and_clips_to_the_image():
    # original 200x100 -> ratio 3.2, pad (0,160)
    out = _tensor([(0, 320, 320, 64, 32, 0, 0.9), (1, 630, 320, 64, 32, 4, 0.9)])
    dets = decode_yolov8(out, conf_thres=0.25, iou_thres=0.45, ratio=3.2, pad=(0.0, 160.0), orig_size=(200, 100))
    assert dets[0].bbox == pytest.approx((90, 45, 110, 55))
    assert dets[1].bbox[2] == pytest.approx(200)  # clipped at the right edge


def test_decode_accepts_the_transposed_layout():
    out = _tensor([(0, 320, 320, 100, 50, 7, 0.9)], transposed=True)
    dets = decode_yolov8(out, conf_thres=0.25, iou_thres=0.45, ratio=1.0, pad=(0, 0), orig_size=(640, 640))
    assert [d.class_id for d in dets] == [7]


def test_decode_rejects_a_model_with_the_wrong_class_count():
    with pytest.raises(ValueError, match="44"):
        decode_yolov8(np.zeros((1, 4 + 10, 100), np.float32), conf_thres=0.25, iou_thres=0.45,
                      ratio=1, pad=(0, 0), orig_size=(640, 640))


def test_decode_caps_the_number_of_detections():
    entries = [(i, 10 + 20 * (i % 30), 10 + 20 * (i // 30), 8, 8, 0, 0.9) for i in range(60)]
    dets = decode_yolov8(_tensor(entries), conf_thres=0.25, iou_thres=0.45, ratio=1, pad=(0, 0),
                         orig_size=(640, 640), max_det=25)
    assert len(dets) == 25


def test_decode_of_an_empty_prediction_is_empty():
    dets = decode_yolov8(_tensor([]), conf_thres=0.25, iou_thres=0.45, ratio=1, pad=(0, 0), orig_size=(64, 64))
    assert dets == []


def test_class_table_matches_contract():
    assert NC == 44
    assert CLASS_BY_ID[40].structural == "branch_left" and CLASS_BY_ID[41].structural == "branch_right"
    assert CLASS_BY_ID[8].mnemonic == "TON" and CLASS_BY_ID[38].mnemonic is None


# ---------------------------------------------------------------- real onnxruntime session
def build_constant_model(path, prediction: np.ndarray, imgsz: int = 640):
    """A real ONNX graph: output = prediction + 0 * mean(images). Exercises onnxruntime end to end."""
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper, numpy_helper

    const = numpy_helper.from_array(prediction.astype(np.float32), name="pred")
    nodes = [
        helper.make_node("Constant", [], ["pred_c"], value=const),
        helper.make_node("ReduceMean", ["images"], ["mean"], keepdims=0),
        helper.make_node("Constant", [], ["zero"], value=numpy_helper.from_array(np.array(0, np.float32))),
        helper.make_node("Mul", ["mean", "zero"], ["zeroed"]),
        helper.make_node("Add", ["pred_c", "zeroed"], ["output0"]),
    ]
    graph = helper.make_graph(
        nodes, "const_yolo",
        [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, imgsz, imgsz])],
        [helper.make_tensor_value_info("output0", TensorProto.FLOAT, list(prediction.shape))],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    onnx.save(model, str(path))
    return path


def test_detector_runs_a_real_onnx_session(tmp_path):
    pred = _tensor([(0, 320, 320, 64, 32, 0, 0.9), (1, 100, 320, 20, 300, 42, 0.8)])
    model = build_constant_model(tmp_path / "tiny.onnx", pred)
    det = YoloOnnxDetector(model, conf=0.25, iou=0.45, threads=1)
    assert det.input_hw == (640, 640)
    assert det.model_name == "tiny.onnx"
    dets = det.detect(Image.new("RGB", (200, 100), "white"))
    assert [d.class_id for d in dets] == [0, 42]
    assert dets[0].bbox == pytest.approx((90, 45, 110, 55))


def test_detector_refuses_a_model_with_the_wrong_output_shape(tmp_path):
    model = build_constant_model(tmp_path / "bad.onnx", np.zeros((1, 4 + 3, 10), np.float32))
    with pytest.raises(ValueError, match="44"):
        YoloOnnxDetector(model)


def test_detector_refuses_a_corrupt_file(tmp_path):
    bad = tmp_path / "corrupt.onnx"
    bad.write_bytes(b"not an onnx model")
    with pytest.raises(Exception):
        YoloOnnxDetector(bad)
