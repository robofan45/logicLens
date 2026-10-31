"""Fixes from the end-to-end evaluation (ml/tools/eval_e2e.py): look-alike duplicates,
box header override and address-aware OCR correction."""
import pytest

from app.engines.base import Detection
from app.engines.ocr import box_mnemonic, normalize_operand
from app.engines.yolo_onnx import suppress_lookalikes

CLS = {"XIC": 0, "XIO": 1, "OTE": 4, "OTL": 6, "NEQ": 17, "LES": 19, "GEQ": 20, "LEQ": 21, "ADD": 22, "RAIL_L": 42, "BR_START": 40}


def det(name, conf, box):
    return Detection(CLS[name], conf, box)


def test_overlapping_boxes_of_different_compare_classes_collapse_to_the_best():
    box = (100, 50, 180, 110)
    out = suppress_lookalikes([det("LEQ", 0.81, box), det("NEQ", 0.55, (101, 51, 179, 111)), det("GEQ", 0.40, (99, 50, 181, 109))])
    assert [d.class_id for d in out] == [CLS["LEQ"]]


def test_contact_and_coil_lookalikes_collapse_but_different_families_do_not():
    out = suppress_lookalikes([
        det("XIC", 0.9, (10, 10, 30, 40)), det("XIO", 0.6, (10, 10, 31, 40)),       # same symbol
        det("OTE", 0.9, (300, 10, 330, 40)), det("OTL", 0.5, (301, 11, 330, 40)),   # same symbol
        det("ADD", 0.7, (10, 10, 30, 40)),                                         # other family: kept
    ])
    assert sorted(d.class_id for d in out) == sorted([CLS["XIC"], CLS["OTE"], CLS["ADD"]])


def test_structural_classes_and_separate_symbols_are_untouched():
    dets = [det("RAIL_L", 0.9, (0, 0, 6, 500)), det("BR_START", 0.8, (2, 0, 8, 120)),
            det("XIC", 0.9, (10, 10, 30, 40)), det("XIC", 0.9, (60, 10, 80, 40))]
    assert len(suppress_lookalikes(dets)) == 4


@pytest.mark.parametrize("text,expected", [
    ("LEQ\nLess Than or Eql (A<=B)\nSource A Level", "LEQ"),
    ("Less Than or Eql (A<=B)\nSource A Level", "LEQ"),
    ("Greater Than or Eql (A>=B)", "GEQ"),
    ("TON\nTimer On Delay", "TON"),
    ("C TU", None),
    ("", None),
    ("Source A Level\nSource B 50", None),
])
def test_box_mnemonic_reads_the_header(text, expected):
    assert box_mnemonic(text) == expected


@pytest.mark.parametrize("raw,expected", [
    ("%10.1", "%I0.1"),          # I read as 1
    ("%l3.4", "%I3.4"),
    ("%O0.3", "%Q0.3"),          # Q read as O
    ("%00.3", "%Q0.3"),
    ("%Q3.6", "%Q3.6"),
    ("%M76.5", "%M76.5"),
    ("%MW1O", "%MW10"),
    ("%IX0.0", "%IX0.0"),
    ("Local:3:1.Data.2", "Local:3:I.Data.2"),
    ("Local:2:0.Data.5", "Local:2:O.Data.5"),
    ("Local:1:I.Data.0", "Local:1:I.Data.0"),
    ("I:1/3", "I:1/3"),           # SLC path unchanged
    ("Start_PB", "Start_PB"),
])
def test_address_aware_ocr_correction(raw, expected):
    assert normalize_operand(raw) == expected
