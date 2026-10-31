"""Contract section 6 conformance: the backend assembler, fed this dataset's ground-truth boxes and
an ideal OCR (``FakeOcr`` returning the rendered strings), must rebuild the ground-truth program.

This checks that the renders follow the layout conventions the assembler assumes, independently
of any trained model. Three assembler gaps are pinned as strict xfails (they flip to XPASS - and
fail - once the backend fixes them, so the xfail must then be removed):
  1. quoted TIA symbols lose their quotes in ocr.normalize_operand ('"Start"' -> 'Start');
  2. a box instruction drawn without its optional last row (IEC ``TON(T1,T#5s)``, ``CTU(C1,10)``)
     gets '?' for the missing slot ('TON(T1,T#5s,?)');
  3. an unconditional output-only rung (``JSR(U:3);``, ``MOV(0,N7:1);``, a centred ``END();``)
     drawn under another rung's outputs is merged into that rung as a connector-less parallel
     output leg (assembler._attach_loose_rows).
"""
import sys
from pathlib import Path

import pytest

from generator.contract import BRANCH_END, BRANCH_START, RAIL_LEFT, RAIL_RIGHT, llt
from generator.dataset import TEXT_ROLES_FOR_OCR, make_sample

BACKEND = Path(__file__).resolve().parents[3] / "backend"


@pytest.fixture(scope="module")
def backend():
    if not (BACKEND / "app" / "engines" / "assembler.py").is_file():
        pytest.skip("backend/ not present")
    sys.path.insert(0, str(BACKEND))
    sys.dont_write_bytecode = True  # read-only use of backend/: leave no __pycache__ behind
    try:
        from app.engines.assembler import assemble
        from app.engines.base import Detection
        from app.engines.ocr import FakeOcr
        from app.program import finalize_rungs
    except Exception as exc:  # pragma: no cover - backend deps missing
        pytest.skip(f"backend not importable: {exc}")
    return assemble, Detection, FakeOcr, finalize_rungs


def _two_operand_box(ins) -> bool:
    return ins["mnemonic"] in ("TON", "TOF", "RTO", "TP", "CTU", "CTD", "CTUD") and len(ins["operands"]) == 2


def operand_gap(meta) -> bool:
    """Gaps 1 and 2 (operand reading)."""
    for ins in meta["instructions"]:
        if any(op.startswith('"') for op in ins["operands"]) or _two_operand_box(ins):
            return True
    return False


def unconditional_gap(meta) -> bool:
    """Gap 3: an output-only rung below the first rung."""
    for r in meta["rungs"][1:]:
        rung = llt.parse_program(r["text"]).rungs[0]
        if not any(i.role == "in" for i in llt.iter_instructions(rung.body)):
            return True
    return False


def known_gap(meta) -> bool:
    return operand_gap(meta) or unconditional_gap(meta)


def run_assembler(backend, meta):
    assemble, Detection, FakeOcr, finalize_rungs = backend
    dets, labels = [], []
    for ins in meta["instructions"]:
        dets.append(Detection(ins["class_id"], 0.95, tuple(ins["box"])))
        for t in ins["texts"]:
            if t["role"] in TEXT_ROLES_FOR_OCR and t["box"] is not None:
                x0, y0, x1, y1 = t["box"]
                labels.append((t["text"], ((x0 + x1) / 2, (y0 + y1) / 2)))
    for st in meta["structures"]:
        dets.append(Detection(st["class_id"], 0.95, tuple(st["box"])))
    result = assemble(None, dets, FakeOcr(labels))
    warnings = list(result.warnings)
    rungs = finalize_rungs(result.rungs, warnings)
    return [r.text for r in rungs], warnings


@pytest.fixture(scope="module")
def clean_metas():
    return [make_sample(11, "train", i, aug="none").meta for i in range(150)]


def test_assembler_rebuilds_ground_truth_from_ground_truth_boxes(backend, clean_metas):
    checked, failures = 0, []
    for meta in clean_metas:
        if known_gap(meta):
            continue
        checked += 1
        texts, warnings = run_assembler(backend, meta)
        expected = [r["text"] for r in meta["rungs"]]
        if texts != expected:
            failures.append((meta["image"], meta["style"], expected, texts, warnings))
    assert checked >= 40, checked
    assert not failures, "\n".join(f"{f[0]} {f[1]}\n  want {f[2]}\n  got  {f[3]}\n  {f[4]}" for f in failures[:5])


def test_known_gap_samples_differ_only_by_the_documented_gaps(backend, clean_metas):
    """With gaps 1 and 2 normalised away, those samples rebuild exactly too."""
    import re
    checked, failures = 0, []
    for meta in clean_metas:
        if not operand_gap(meta) or unconditional_gap(meta):
            continue
        checked += 1
        texts, _ = run_assembler(backend, meta)
        norm = [re.sub(r",\?\)", ")", t) for t in texts]          # gap 2: trailing '?' slot
        expected = [r["text"].replace('"', "") for r in meta["rungs"]]  # gap 1: quotes dropped
        if norm != expected:
            failures.append((meta["image"], expected, texts))
    assert checked >= 10, checked
    assert not failures, failures[:3]


@pytest.mark.xfail(strict=True, reason="backend gap: ocr.normalize_operand strips the quotes of TIA symbols")
def test_gap_quoted_symbols_keep_their_quotes(backend):
    meta = _synthetic_meta('XIC("Start_PB")OTE("Motor_On");')
    texts, _ = run_assembler(backend, meta)
    assert texts == ['XIC("Start_PB")OTE("Motor_On");']


@pytest.mark.xfail(strict=True, reason="backend gap: parse_box_text emits '?' for an optional slot that is not drawn")
def test_gap_two_operand_iec_timer(backend):
    meta = _synthetic_meta("XIC(START)TON(T_FILL,T#5s);", platform="generic_iec", style="iec")
    texts, _ = run_assembler(backend, meta)
    assert texts == ["XIC(START)TON(T_FILL,T#5s);"]


@pytest.mark.xfail(strict=True, reason="backend gap: an unconditional rung under another rung's outputs is merged "
                                       "into it as a parallel output leg (_attach_loose_rows)")
def test_gap_unconditional_rung_stays_a_rung(backend):
    meta = _synthetic_meta("XIC(I:1/0)OTE(O:2/0);\nMOV(N7:0,N7:1);\nXIC(I:1/1)OTE(O:2/1);",
                           platform="rockwell_slc", style="rslogix500")
    texts, _ = run_assembler(backend, meta)
    assert texts == ["XIC(I:1/0)OTE(O:2/0);", "MOV(N7:0,N7:1);", "XIC(I:1/1)OTE(O:2/1);"]


def test_gap_free_categories_are_well_represented(clean_metas):
    """Guard: the strict test above must keep seeing a meaningful share of the data."""
    share = sum(not known_gap(m) for m in clean_metas) / len(clean_metas)
    assert share >= 0.25, share


def _synthetic_meta(program: str, platform: str = "siemens_tia", style: str = "tia"):
    import random
    from generator.compose import Composer
    from generator.styles import sample_style
    from generator.dataset import _finish
    for k in range(20):
        rng = random.Random(f"gap:{program}:{k}")
        st = sample_style(style, rng, platform)
        comp = Composer(st, platform, rng, 736).compose(program)
        if comp is not None:
            return _finish(0, "test", 0, rng, comp, 736, "none").meta
    raise RuntimeError("could not compose")
