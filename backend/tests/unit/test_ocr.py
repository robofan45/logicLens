import io

import pytest
from PIL import Image, ImageDraw

from app.engines.ocr import (
    FakeOcr, OcrRequest, TesseractOcr, join_split_address, normalize_operand, parse_box_text, parse_tsv, vote,
)


@pytest.mark.parametrize("raw,expected", [
    ("I:1", "I:1"), (" I:1 ", "I:1"), ("1:1", "I:1"), ("l:1", "I:1"), ("I:]", "I:1"), ("I:l", "I:1"),
    ("0:2", "O:2"), ("Q:2", "O:2"), ("Q2:0", "Q2:0"), ("L9:3", "L9:3"), ("QO:2", "O:2"), ("o:2", "O:2"), ("B:0", "B:0"), ("B:O", "B:0"),
    ("B3:0/1", "B3:0/1"), ("B3:O/l", "B3:0/1"), ("N7:1O", "N7:10"), ("T4:0.dn", "T4:0.DN"), ("T4:0.DN", "T4:0.DN"),
    ("I:1/1", "I:1/1"), ("Start_PB", "Start_PB"), ("Motor.Run", "Motor.Run"), ("%I0.0", "%I0.0"),
    ("Local:1:I.Data.0", "Local:1:I.Data.0"), ("500", "500"), ("0.01", "0.01"), ("500<", "500"),
    ("", ""), ("~~", ""), ("a b", "ab"),
])
def test_normalize_operand(raw, expected):
    assert normalize_operand(raw) == expected


@pytest.mark.parametrize("above,below,expected", [
    ("I:1", "1", "I:1/1"), ("B3:0", "15", "B3:0/15"), ("O:2", "", "O:2"), ("I:1/1", "3", "I:1/1"),
    ("Start_PB", "4", "Start_PB"), ("T4:0.DN", "1", "T4:0.DN"), ("I:1", "x", "I:1"), ("", "1", ""),
])
def test_rslogix_split_address_join(above, below, expected):
    assert join_split_address(above, below) == expected


def test_vote_prefers_agreeing_plausible_candidates():
    assert vote(["I:1", "Il", "I:1"]) == "I:1"
    assert vote(["Il", "I:]", "1:1"]) == "I:1"       # normalised candidates agree
    assert vote(["", "B:0", ""]) == "B:0"
    assert vote(["", "", ""]) == ""
    assert vote(["Motor_Run", "Motor_Run", "MotorRun"]) == "Motor_Run"


@pytest.mark.parametrize("mnemonic,text,expected", [
    ("TON", "TON\nTimer On Delay\nTimer T4:0\nTime Base 0.01\nPreset 500<\nAccum 0<", ["T4:0", "0.01", "500", "0"]),
    ("TON", "TON\nTimer Delay_T\nPreset 5000\nAccum 0", ["Delay_T", "5000", "0"]),
    ("CTU", "CTU\nCount Up\nCounter C5:0\nPreset 10<\nAccum 0<", ["C5:0", "10", "0"]),
    ("MOV", "MOV\nMove\nSource N7:0\n0<\nDest N7:1\n0<", ["N7:0", "N7:1"]),
    ("ADD", "ADD\nSource A N7:0\nSource B 5\nDest N7:2", ["N7:0", "5", "N7:2"]),
    ("GRT", "GRT\nGreater Than (A>B)\nSource A Level\nSource B 80", ["Level", "80"]),
    ("EQU", "EQU\nSource A N7:0\n", ["N7:0", "?"]),
    ("OSR", "OSR\nStorage Bit B3:0/0\nOutput Bit B3:0/1", ["B3:0/0", "B3:0/1"]),
    ("JSR", "JSR\nJump To Subroutine\nRoutine Name Fill_Seq", ["Fill_Seq"]),
    ("TON", "garbage line only", ["?", "?", "?"]),
])
def test_box_instruction_text_maps_to_operand_order(mnemonic, text, expected):
    assert parse_box_text(mnemonic, text) == expected


def test_parse_tsv_groups_words_into_bands():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t10\t12\t30\t10\t91\tI:1\n"
           "5\t1\t1\t1\t1\t2\t60\t13\t8\t10\t88\t1\n"
           "5\t1\t2\t1\t1\t1\t10\t52\t30\t10\t90\tB:0\n"
           "4\t1\t2\t1\t1\t0\t10\t52\t30\t10\t-1\t\n"
           "5\t1\t3\t1\t1\t1\t10\t200\t30\t10\t90\tstray\n")
    bands = [(0, 30), (40, 70)]
    assert parse_tsv(tsv, bands, multiline=False) == ["I:1 1", "B:0"]


def test_parse_tsv_multiline_keeps_line_breaks():
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t10\t10\t30\t10\t91\tTimer\n"
           "5\t1\t1\t1\t1\t2\t50\t10\t30\t10\t91\tT4:0\n"
           "5\t1\t1\t1\t2\t1\t10\t30\t30\t10\t91\tPreset\n"
           "5\t1\t1\t1\t2\t2\t50\t31\t30\t10\t91\t500\n")
    assert parse_tsv(tsv, [(0, 60)], multiline=True) == ["Timer T4:0\nPreset 500"]


def test_fake_ocr_reads_labels_inside_regions():
    ocr = FakeOcr([("I:1", (100, 50)), ("1", (104, 90)), ("B:0", (300, 50))])
    reqs = [OcrRequest("a", (80, 40, 120, 60), "operand"), OcrRequest("b", (80, 80, 120, 100), "digits"),
            OcrRequest("c", (0, 0, 10, 10), "operand")]
    assert ocr.read(None, reqs) == {"a": "I:1", "b": "1", "c": ""}


def _text_image(lines, size=(220, 60)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((5, 5 + 20 * i), line, fill="black")
    return img


def test_tesseract_runner_is_called_with_stdin_png_and_no_temp_files():
    calls = []

    def fake_runner(argv, data, timeout):
        calls.append((argv, data[:8], timeout))
        return ""

    ocr = TesseractOcr(cmd="/usr/bin/tesseract-x", timeout_s=7, runner=fake_runner)
    img = _text_image(["I:1"])
    out = ocr.read(img, [OcrRequest("k", (0, 0, 60, 25), "operand"), OcrRequest("d", (0, 25, 60, 50), "digits")])
    assert out == {"k": "", "d": ""}
    assert calls, "tesseract was not invoked"
    for argv, head, timeout in calls:
        assert argv[:3] == ["/usr/bin/tesseract-x", "stdin", "stdout"]
        assert head == b"\x89PNG\r\n\x1a\n"
        assert timeout == 7


def test_tesseract_failure_degrades_to_unreadable_not_an_exception():
    def broken_runner(argv, data, timeout):
        raise OSError("tesseract missing")

    ocr = TesseractOcr(runner=broken_runner)
    assert ocr.read(_text_image(["x"]), [OcrRequest("k", (0, 0, 50, 20), "operand")]) == {"k": ""}


def test_empty_request_list_does_not_call_tesseract():
    def runner(argv, data, timeout):  # pragma: no cover - must not be called
        raise AssertionError("called")

    assert TesseractOcr(runner=runner).read(_text_image(["x"]), []) == {}


def test_region_outside_the_image_is_clipped():
    ocr = TesseractOcr(runner=lambda argv, data, timeout: "")
    assert ocr.read(_text_image(["x"]), [OcrRequest("k", (-50, -50, 5000, 5000), "block"),
                                         OcrRequest("z", (500, 500, 600, 600), "operand")]) == {"k": "", "z": ""}


# ---------------------------------------------------------------- text isolation helpers
import numpy as np  # noqa: E402

from app.engines.ocr import isolate_text, lone_stroke  # noqa: E402


def _ink_crop(draw_fn, size=(60, 30)):
    img = Image.new("RGB", size, "white")
    draw_fn(ImageDraw.Draw(img))
    return img


def test_isolate_text_drops_symbol_strokes_touching_the_symbol_edge():
    # text block near the top, two bracket strokes rising from the bottom edge (the symbol)
    crop = _ink_crop(lambda d: (d.rectangle([20, 4, 34, 12], fill="black"),
                                d.line([(18, 22), (18, 29)], fill="black", width=2),
                                d.line([(40, 22), (40, 29)], fill="black", width=2)))
    ink = isolate_text(crop, "bottom")
    assert ink.shape[0] < 20                       # cut down to the text band
    assert (ink < 128).sum() >= 14 * 8             # text kept
    assert (ink[-3:] == 255).all()                 # bracket strokes gone
    assert isolate_text(crop, None).shape == (30, 60)  # no edge hint: nothing is cut


def test_isolate_text_falls_back_when_everything_touches_the_edge():
    crop = _ink_crop(lambda d: d.line([(30, 0), (30, 29)], fill="black", width=2))
    assert isolate_text(crop, "top").shape == (30, 60)


def test_lone_stroke_detects_a_bare_one_but_not_other_glyphs():
    one = np.full((16, 20), 255, np.uint8)
    one[3:13, 9:11] = 0
    assert lone_stroke(one)
    seven = one.copy()
    seven[3, 4:11] = 0
    assert not lone_stroke(seven)
    blank = np.full((16, 20), 255, np.uint8)
    assert not lone_stroke(blank)
    two_bars = one.copy()
    two_bars[3:13, 15:17] = 0
    assert not lone_stroke(two_bars)


def test_digits_fall_back_to_one_for_a_lone_stroke():
    img = Image.new("RGB", (40, 30), "white")
    ImageDraw.Draw(img).line([(20, 6), (20, 20)], fill="black", width=2)
    ocr = TesseractOcr(runner=lambda argv, data, timeout: "")
    assert ocr.read(img, [OcrRequest("d", (0, 0, 40, 30), "digits")]) == {"d": "1"}
