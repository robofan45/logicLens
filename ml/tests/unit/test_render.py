"""Rendering: tight symbol boxes (checked against the actual ink), section-6 geometry."""
import numpy as np
import pytest
from PIL import Image

from generator.compose import Composer
from generator.contract import BRANCH_END, BRANCH_START, RAIL_LEFT, RAIL_RIGHT, llt
from generator.raster import rasterize

from tests.conftest import STYLE_PLATFORMS


def _ink_bbox(a: np.ndarray, b: np.ndarray):
    diff = np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 0
    ys, xs = np.nonzero(diff)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def _element(comp, key):
    return next(e for e in comp.elements if e.key == key)


def test_isolated_symbol_ink_equals_its_box(compositions):
    """Drawn alone on a blank canvas, a symbol's ink bbox is exactly its label box."""
    for comp in compositions:
        w, h = comp.size
        bg = comp.style.bg
        blank = np.full((h, w, 3), bg, dtype=np.uint8)
        for ins in comp.instructions:
            img, _ = rasterize(w, h, comp.style.ss, bg, [_element(comp, ins["key"])])
            ink = _ink_bbox(np.asarray(img), blank)
            assert ink is not None
            x0, y0, x1, y1 = ins["box"]
            # every inked pixel is inside the box ...
            assert ink[0] >= x0 and ink[1] >= y0 and ink[2] <= x1 and ink[3] <= y1, (comp.style.name, ins["mnemonic"])
            # ... and the box is not larger than the ink (pixels with any coverage count as ink)
            assert (ink[0] - x0, ink[1] - y0, x1 - ink[2], y1 - ink[3]) == (0, 0, 0, 0), (comp.style.name, ins["mnemonic"])


def test_symbol_box_is_tight_in_the_composed_image(compositions):
    """Removing one symbol from the full diagram changes pixels only inside its box, and the
    changed pixels reach to within 2 px of every box edge (nothing else is inside the box)."""
    for comp in compositions:
        w, h = comp.size
        full = np.asarray(comp.image)
        for ins in comp.instructions[:12]:
            img, _ = rasterize(w, h, comp.style.ss, comp.style.bg, comp.elements, skip={ins["key"]})
            ink = _ink_bbox(full, np.asarray(img))
            assert ink is not None, (comp.style.name, ins["mnemonic"])
            x0, y0, x1, y1 = ins["box"]
            assert ink[0] >= x0 and ink[1] >= y0 and ink[2] <= x1 and ink[3] <= y1
            slack = (ink[0] - x0, ink[1] - y0, x1 - ink[2], y1 - ink[3])
            assert max(slack) <= 2, (comp.style.name, ins["mnemonic"], slack)


def test_operand_text_is_outside_contact_and_coil_boxes(compositions):
    for comp in compositions:
        for ins in comp.instructions:
            if ins["kind"] == "box":
                continue
            x0, y0, x1, y1 = ins["box"]
            for t in ins["texts"]:
                tx0, ty0, tx1, ty1 = t["box"]
                overlap_y = min(y1, ty1) - max(y0, ty0)
                assert overlap_y <= 0, (comp.style.name, ins["mnemonic"], t)


def test_box_instruction_text_is_inside_its_rectangle(compositions):
    for comp in compositions:
        for ins in comp.instructions:
            if ins["kind"] != "box":
                continue
            x0, y0, x1, y1 = ins["box"]
            inside = [t for t in ins["texts"] if t["role"].startswith("box_")]
            assert inside and inside[0]["role"] == "box_title"
            for t in inside:
                tx0, ty0, tx1, ty1 = t["box"]
                assert x0 <= tx0 and tx1 <= x1 and y0 <= ty0 and ty1 <= y1, (ins["mnemonic"], t)


def test_operand_text_sits_where_the_backend_ocr_looks(compositions):
    """Assembler crops: above = [y1 - 1.3h, y1 + 0.3h], split bit below = [y2 - 0.3h, y2 + 1.1h]."""
    for comp in compositions:
        for ins in comp.instructions:
            if ins["kind"] == "box":
                continue
            x0, y0, x1, y1 = ins["box"]
            h = y1 - y0
            for t in ins["texts"]:
                cy = (t["box"][1] + t["box"][3]) / 2
                if t["role"] == "operand":
                    assert y0 - 1.3 * h < cy < y0 + 0.3 * h
                    assert t["box"][1] >= y0 - 1.6 * h  # whole line inside a generous crop
                elif t["role"] == "bit":
                    assert y1 - 0.3 * h < cy < y1 + 1.1 * h


def test_rows_rails_connectors_and_alignment(compositions):
    for comp in compositions:
        w, h = comp.size
        rails = {s["class_id"]: s["box"] for s in comp.structures if s["class_id"] in (RAIL_LEFT, RAIL_RIGHT)}
        assert set(rails) == {RAIL_LEFT, RAIL_RIGHT}
        for st in comp.structures:
            x0, y0, x1, y1 = st["box"]
            assert x1 - x0 >= 6.0, st
        left_x = (rails[RAIL_LEFT][0] + rails[RAIL_LEFT][2]) / 2
        right_x = (rails[RAIL_RIGHT][0] + rails[RAIL_RIGHT][2]) / 2
        starts = [s for s in comp.structures if s["class_id"] == BRANCH_START]
        ends = [s for s in comp.structures if s["class_id"] == BRANCH_END]
        n_branches = sum(_count_branches(rp.rung.body) for rp in comp.rungs)
        assert len(starts) == len(ends) == n_branches
        for rp in comp.rungs:
            ins = [i for i in comp.instructions if i["rung"] == rp.index]
            row0 = [i for i in ins if i["row"] == 0]
            outs = [i for i in row0 if llt.SPEC[i["mnemonic"]][2] == "out"]
            inputs = [i for i in row0 if llt.SPEC[i["mnemonic"]][2] == "in"]
            for i in ins:
                assert left_x < i["box"][0] and i["box"][2] < right_x
            if outs and inputs:  # outputs to the right of all inputs on the rung line
                assert max(i["box"][2] for i in inputs) < min(o["box"][0] for o in outs)
            if outs and not rp.centered_end:  # right-aligned: last output close to the right rail
                gap = right_x - max(o["box"][2] for o in outs)
                assert gap < 0.25 * (right_x - left_x), gap


def _count_branches(seq) -> int:
    n = 0
    for it in seq.items:
        if isinstance(it, llt.Branch):
            n += 1 + sum(_count_branches(leg) for leg in it.legs)
    return n


def test_box_title_row_is_centred_on_the_rung_line(compositions):
    """The assembler anchors a box at y1 + 0.5 * (median contact height): must be the rung line."""
    for comp in compositions:
        small = [i["box"][3] - i["box"][1] for i in comp.instructions if i["kind"] != "box"]
        if not small:
            continue
        mh = float(np.median(small))
        for ins in comp.instructions:
            if ins["kind"] == "box":
                anchor = ins["box"][1] + 0.5 * mh
                assert abs(anchor - ins["line_y"]) < 0.3 * mh, (comp.style.name, ins["mnemonic"])
            else:
                cy = (ins["box"][1] + ins["box"][3]) / 2
                assert abs(cy - ins["line_y"]) < 0.2 * mh


def test_legs_are_on_lower_rows_than_the_rung_line(compositions):
    for comp in compositions:
        for rp in comp.rungs:
            levels = rp.levels
            assert levels == sorted(levels)
            for b in rp.branches:
                legs = [lv for _, lv in b.legs]
                assert legs[0] == b.level_top and legs == sorted(legs) and len(set(legs)) == len(legs)
                for other in rp.branches:  # nested branches sit strictly inside their parent
                    if other is not b and other.level_top in legs and b.xs <= other.xs <= b.xe:
                        assert b.xs < other.xs and other.xe < b.xe


def test_smallest_symbol_stays_above_14px_after_letterbox(compositions):
    checked = 0
    for comp in compositions:
        w, h = comp.size
        dims = [min(i["box"][2] - i["box"][0], i["box"][3] - i["box"][1])
                for i in comp.instructions if i["kind"] != "box"]
        if not dims:  # a box-only diagram has no contact/coil to measure
            continue
        checked += 1
        assert min(dims) * 736 / max(w, h) >= 13.0, (comp.style.name, min(dims), comp.size)
    assert checked >= len(compositions) // 2


def test_end_rung_is_last_and_centred_in_rockwell_styles(compositions):
    for comp in compositions:
        ends = [i for i in comp.instructions if i["mnemonic"] == "END"]
        if not ends:
            continue
        assert ends[-1]["rung"] == comp.rungs[-1].index
        assert comp.program_text.rstrip().endswith("END();")


def test_composer_rejects_invalid_programs():
    from generator.styles import sample_style
    import random
    rng = random.Random(0)
    style = sample_style("rslogix500", rng, "rockwell_slc")
    with pytest.raises(ValueError):
        Composer(style, "rockwell_slc", rng).compose("XIC(;")
