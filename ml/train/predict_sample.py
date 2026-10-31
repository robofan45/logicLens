"""Run the ONNX detector on the real RSLogix 500 screenshot and report what it gets right.

    python train/predict_sample.py --model models/logiclens-yolov8n.onnx

Writes ml/reports/sample_prediction.png (detections drawn on a 2x upscale, ground-truth boxes in
grey) and ml/reports/sample_prediction.json (detections, matching against the hand-labelled
boxes used by backend/tests/integration/test_sample_assembler.py, and - when tesseract is
installed - the LLT the backend assembler builds from these detections).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ML_DIR = Path(__file__).resolve().parent.parent
REPO = ML_DIR.parent
sys.path.insert(0, str(ML_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

SAMPLE = REPO / "samples" / "ladder_logic_program_PLC1.webp"
SAMPLE_TRUTH = ["XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);", "[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);",
                "XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);"]
# Hand-labelled tight boxes for the sample (same as backend/tests/integration/test_sample_assembler.py)
HAND_LABELS = [
    ("Power_Rail_Left", (82, 16, 89, 469)), ("Power_Rail_Right", (830, 16, 837, 469)),
    ("NO_Contact", (162, 73, 186, 91)), ("NO_Contact", (263, 73, 286, 91)), ("Output_Coil", (770, 73, 799, 90)),
    ("NO_Contact", (211, 180, 235, 198)), ("Output_Coil", (770, 180, 799, 197)),
    ("NO_Contact", (211, 273, 235, 291)),
    ("Branch_Start", (160, 186, 167, 285)), ("Branch_End", (284, 186, 291, 285)),
    ("NC_Contact", (162, 365, 188, 383)), ("NC_Contact", (259, 365, 285, 383)),
    ("NC_Contact", (357, 365, 383, 383)), ("Output_Coil", (770, 366, 799, 383)),
]


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(dets, names):
    """Greedy one-to-one matching of detections to hand labels by IoU (>= 0.5 for a hit)."""
    pairs, used = [], set()
    for gi, (gname, gbox) in enumerate(HAND_LABELS):
        best, bj = 0.0, None
        for j, (cid, conf, box) in enumerate(dets):
            if j in used:
                continue
            v = iou(gbox, box)
            if v > best:
                best, bj = v, j
        if bj is not None and best >= 0.3:
            used.add(bj)
            pairs.append({"truth": gname, "pred": names[dets[bj][0]], "conf": round(dets[bj][1], 3),
                          "iou": round(best, 3), "class_ok": names[dets[bj][0]] == gname, "hit": best >= 0.5})
        else:
            pairs.append({"truth": gname, "pred": None, "conf": None, "iou": round(best, 3), "class_ok": False,
                          "hit": False})
    extra = [{"pred": names[d[0]], "conf": round(d[1], 3), "box": [round(v, 1) for v in d[2]]}
             for j, d in enumerate(dets) if j not in used]
    return pairs, extra


def assemble_llt(image, dets):
    if shutil.which("tesseract") is None:
        return None, ["tesseract not installed"]
    try:
        sys.path.insert(0, str(REPO / "backend"))
        sys.dont_write_bytecode = True  # read-only use of backend/: leave no __pycache__ behind
        from app.engines.assembler import assemble
        from app.engines.base import Detection
        from app.engines.ocr import TesseractOcr
        from app.program import finalize_rungs
    except Exception as exc:  # pragma: no cover
        return None, [f"backend not importable: {exc}"]
    result = assemble(image, [Detection(c, p, b) for c, p, b in dets], TesseractOcr())
    warnings = list(result.warnings)
    rungs = finalize_rungs(result.rungs, warnings)
    return [r.text for r in rungs], warnings


def draw(image, dets, names, path: Path, scale: int = 2):
    from generator.preview import color_for
    big = image.convert("RGB").resize((image.width * scale, image.height * scale), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:  # pragma: no cover
        font = ImageFont.load_default()
    for _, box in HAND_LABELS:
        d.rectangle([v * scale for v in box], outline=(170, 170, 170), width=1)
    for cid, conf, box in dets:
        c = color_for(cid)
        b = [v * scale for v in box]
        d.rectangle(b, outline=c, width=2)
        label = f"{names[cid]} {conf:.2f}"
        d.text((b[0], max(0, b[1] - 15)), label, fill=c, font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    big.save(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", type=Path, default=ML_DIR / "models" / "logiclens-yolov8n.onnx")
    ap.add_argument("--image", type=Path, default=SAMPLE)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", type=Path, default=ML_DIR / "reports" / "sample_prediction.png")
    a = ap.parse_args(argv)
    from onnx_infer import OnnxDetector
    from generator.contract import NAMES

    image = Image.open(a.image).convert("RGB")
    det = OnnxDetector(a.model, threads=2, conf=a.conf)
    dets = det(image)
    dets.sort(key=lambda d: (d[2][1], d[2][0]))
    pairs, extra = match(dets, NAMES)
    llt, warnings = assemble_llt(image, dets)
    draw(image, dets, NAMES, a.out)
    report = {
        "image": a.image.name, "model": a.model.name, "conf": a.conf,
        "detections": [{"class": NAMES[c], "conf": round(p, 3), "box": [round(v, 1) for v in b]} for c, p, b in dets],
        "hand_labels": len(HAND_LABELS), "hits": sum(p["hit"] and p["class_ok"] for p in pairs),
        "localised_wrong_class": sum(p["hit"] and not p["class_ok"] for p in pairs),
        "missed": [p["truth"] for p in pairs if not p["hit"]], "matches": pairs, "false_positives": extra,
        "assembled_llt": llt, "assembler_warnings": warnings, "ground_truth_llt": SAMPLE_TRUTH,
        "llt_exact": llt == SAMPLE_TRUTH if llt is not None else None,
    }
    a.out.with_suffix(".json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("hits", "hand_labels", "localised_wrong_class", "missed",
                                              "assembled_llt", "llt_exact")}, indent=1))
    print("false positives:", json.dumps(extra))
    return 0


if __name__ == "__main__":
    sys.exit(main())
