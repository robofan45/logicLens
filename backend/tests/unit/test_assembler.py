"""Assembler: hand-built detection lists (contract section 6 layout) -> canonical LLT rungs."""
import pytest

from app.engines.assembler import assemble
from app.engines.base import CLASSES, Detection
from app.engines.ocr import FakeOcr
from app.program import finalize_rungs

ID = {c.name: c.id for c in CLASSES}
H = 18   # symbol height
W = 24   # symbol width


def sym(name, x, row_y, w=W, h=H, conf=0.9):
    return Detection(ID[name], conf, (x, row_y - h / 2, x + w, row_y + h / 2))


def box(name, x1, y1, x2, y2, conf=0.9):
    return Detection(ID[name], conf, (x1, y1, x2, y2))


def conn(kind, x, y_top, y_bottom):
    return Detection(ID[kind], 0.9, (x - 3, y_top - 4, x + 3, y_bottom + 4))


def rails(y_top=20, y_bottom=600):
    return [box("Power_Rail_Left", 47, y_top, 53, y_bottom), box("Power_Rail_Right", 847, y_top, 853, y_bottom)]


def above(text, d):
    return (text, (d.cx, d.bbox[1] - 7))


def below(text, d):
    return (text, (d.cx + 4, d.bbox[3] + 6))


def run(dets, labels, ocr=True):
    result = assemble(None, dets, FakeOcr(labels) if ocr else None)
    warnings = list(result.warnings)
    rungs = finalize_rungs(result.rungs, warnings)
    return [r.text for r in rungs], warnings, rungs


def test_series_rung():
    a, b, c = sym("NO_Contact", 100, 100), sym("NC_Contact", 200, 100), sym("Output_Coil", 760, 100)
    texts, warnings, rungs = run(rails() + [a, b, c], [above("Start", a), above("Stop", b), above("Motor", c)])
    assert texts == ["XIC(Start)XIO(Stop)OTE(Motor);"]
    assert warnings == []
    assert [e.bbox for e in rungs[0].elements] == [list(a.bbox), list(b.bbox), list(c.bbox)]
    assert 80 <= rungs[0].confidence <= 100


def test_rslogix_split_addresses_are_joined():
    a, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100)
    texts, _, _ = run([a, c], [above("I:1", a), below("1", a), above("B:0", c), below("1", c)])
    assert texts == ["XIC(I:1/1)OTE(B:0/1);"]


def test_seal_in_branch():
    start, motor, remote = sym("NO_Contact", 100, 100), sym("NO_Contact", 190, 100), sym("NO_Contact", 190, 190)
    stop, coil = sym("NC_Contact", 320, 100), sym("Output_Coil", 760, 100)
    dets = rails() + [start, motor, remote, stop, coil,
                      conn("Branch_Start", 160, 100, 190), conn("Branch_End", 250, 100, 190)]
    labels = [above("Start_PB", start), above("Motor_Run", motor), above("Remote_Start", remote),
              above("Stop_PB", stop), above("Motor_Run", coil)]
    texts, warnings, _ = run(dets, labels)
    assert texts == ["XIC(Start_PB)[XIC(Motor_Run),XIC(Remote_Start)]XIO(Stop_PB)OTE(Motor_Run);"]
    assert warnings == []


def test_parallel_outputs_drawn_as_output_branch():
    a, b, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 700, 100), sym("Set_Coil", 700, 190)
    dets = [a, b, c, conn("Branch_Start", 660, 100, 190), conn("Branch_End", 760, 100, 190)]
    texts, _, _ = run(dets, [above("A", a), above("B", b), above("C", c)])
    assert texts == ["XIC(A)[OTE(B),OTL(C)];"]


def test_slc_timer_box_operands_are_read_from_inside_the_box():
    a = sym("NO_Contact", 100, 100)
    ton = box("TON_Timer", 600, 91, 760, 190)
    lines = ["TON", "Timer On Delay", "Timer T4:0", "Time Base 0.01", "Preset 500<", "Accum 0<"]
    labels = [above("I:1", a), below("0", a)] + [(t, (640, 100 + 15 * i)) for i, t in enumerate(lines)]
    texts, _, _ = run([a, ton], labels)
    assert texts == ["XIC(I:1/0)TON(T4:0,0.01,500,0);"]


def test_logix_style_box_instructions():
    a = sym("NO_Contact", 100, 100)
    mov = box("MOV_Move", 400, 91, 520, 170)
    ctu = box("CTU_Counter", 600, 91, 760, 170)
    labels = [above("Run", a), ("MOV", (420, 98)), ("Source Speed_SP", (440, 115)), ("Dest Drive_Ref", (440, 140)),
              ("CTU", (620, 98)), ("Counter Parts", (640, 115)), ("Preset 100", (640, 130)), ("Accum 0", (640, 145))]
    texts, _, _ = run([a, mov, ctu], labels)
    assert texts == ["XIC(Run)MOV(Speed_SP,Drive_Ref)CTU(Parts,100,0);"]


def test_unreadable_operands_become_question_marks_with_lower_confidence():
    a, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100)
    texts, warnings, rungs = run([a, c], [above("Motor", c)])
    assert texts == ["XIC(?)OTE(Motor);"]
    assert any("could not be read" in w for w in warnings)
    assert rungs[0].elements[0].confidence < rungs[0].elements[1].confidence


def test_garbage_ocr_text_is_not_trusted():
    a, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100)
    texts, _, _ = run([a, c], [above("@@ ;;", a), above("Motor", c)])
    assert texts == ["XIC(?)OTE(Motor);"]


def test_rungs_are_banded_by_y_and_numbered_top_down():
    r1 = [sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100)]
    r2 = [sym("NC_Contact", 100, 300), sym("Output_Coil", 760, 300)]
    labels = [above("A", r1[0]), above("B", r1[1]), above("C", r2[0]), above("D", r2[1])]
    texts, _, rungs = run(rails() + r2 + r1, labels)
    assert texts == ["XIC(A)OTE(B);", "XIO(C)OTE(D);"]
    assert [r.number for r in rungs] == [0, 1]


def test_a_slightly_tilted_rung_stays_one_rung():
    dets = [sym("NO_Contact", 100 + 120 * i, 100 + 4 * i) for i in range(5)] + [sym("Output_Coil", 760, 124)]
    labels = [above(f"T{i}", d) for i, d in enumerate(dets)]
    texts, _, _ = run(dets, labels)
    assert texts == ["XIC(T0)XIC(T1)XIC(T2)XIC(T3)XIC(T4)OTE(T5);"]


def test_missing_connectors_infer_a_parallel_leg_from_layout():
    a, b, c = sym("NO_Contact", 200, 100), sym("NO_Contact", 200, 190), sym("Output_Coil", 760, 100)
    texts, warnings, rungs = run([a, b, c], [above("A", a), above("B", b), above("C", c)])
    assert texts == ["[XIC(A),XIC(B)]OTE(C);"]
    assert any("inferred" in w for w in warnings)
    assert rungs[0].confidence < 90


def test_missing_connectors_infer_a_parallel_output():
    a, b, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100), sym("Output_Coil", 760, 190)
    texts, _, _ = run([a, b, c], [above("A", a), above("B", b), above("C", c)])
    assert texts == ["XIC(A)[OTE(B),OTE(C)];"]


def test_nested_branch_on_the_first_leg():
    a, b, c, d = (sym("NO_Contact", 100, 100), sym("NO_Contact", 200, 100), sym("NO_Contact", 200, 190),
                  sym("NO_Contact", 200, 280))
    e = sym("Output_Coil", 760, 100)
    dets = [a, b, c, d, e, conn("Branch_Start", 150, 100, 280), conn("Branch_Start", 175, 100, 190),
            conn("Branch_End", 245, 100, 190), conn("Branch_End", 270, 100, 280)]
    texts, warnings, _ = run(dets, [above(t, x) for t, x in zip("ABCDE", (a, b, c, d, e))])
    assert texts == ["XIC(A)[[XIC(B),XIC(C)],XIC(D)]OTE(E);"]
    assert warnings == []


def test_nested_branch_on_a_lower_leg():
    a, b, c, d = (sym("NO_Contact", 130, 100), sym("NO_Contact", 130, 190), sym("NO_Contact", 200, 190),
                  sym("NO_Contact", 200, 280))
    e = sym("Output_Coil", 760, 100)
    dets = [a, b, c, d, e, conn("Branch_Start", 100, 100, 190), conn("Branch_Start", 170, 190, 280),
            conn("Branch_End", 240, 190, 280), conn("Branch_End", 270, 100, 190)]
    texts, _, _ = run(dets, [above(t, x) for t, x in zip("ABCDE", (a, b, c, d, e))])
    assert texts == ["[XIC(A),XIC(B)[XIC(C),XIC(D)]]OTE(E);"]


def test_branch_with_an_empty_wire_leg():
    a, c = sym("NO_Contact", 200, 100), sym("Output_Coil", 760, 100)
    dets = [a, c, conn("Branch_Start", 160, 100, 190), conn("Branch_End", 250, 100, 190)]
    texts, _, _ = run(dets, [above("A", a), above("C", c)])
    assert texts == ["[XIC(A),]OTE(C);"]


def test_unpaired_connector_is_reported_and_ignored():
    a, c = sym("NO_Contact", 200, 100), sym("Output_Coil", 760, 100)
    texts, warnings, _ = run([a, c, conn("Branch_Start", 160, 100, 190)], [above("A", a), above("C", c)])
    assert texts == ["XIC(A)OTE(C);"]
    assert any("connector" in w for w in warnings)


def test_coil_style_and_operandless_instructions():
    a, res, jmp = sym("NO_Contact", 100, 100), sym("RES_Reset", 600, 100), sym("JMP_Jump", 700, 100)
    b, mcr = sym("NO_Contact", 100, 300), sym("MCR_MasterControl", 760, 300)
    labels = [above("A", a), above("T4:0", res), above("Q2:0", jmp), above("B", b)]
    texts, _, _ = run([a, res, jmp, b, mcr], labels)
    assert texts == ["XIC(A)RES(T4:0)JMP(Q2:0);", "XIC(B)MCR();"]


def test_ocr_disabled_gives_question_marks_and_a_warning():
    a, c = sym("NO_Contact", 100, 100), sym("Output_Coil", 760, 100)
    texts, warnings, _ = run([a, c], [], ocr=False)
    assert texts == ["XIC(?)OTE(?);"]
    assert any("OCR" in w for w in warnings)


def test_structural_only_or_empty_detections_give_no_rungs():
    for dets in ([], rails(), [box("Horizontal_Wire", 0, 0, 100, 3)]):
        result = assemble(None, dets, FakeOcr([]))
        assert result.rungs == []
        assert result.warnings


def test_neighbour_text_is_not_stolen_by_the_next_symbol():
    a, b, c = sym("NO_Contact", 100, 100), sym("NO_Contact", 160, 100), sym("Output_Coil", 760, 100)
    texts, _, _ = run([a, b, c], [above("Left_Tag", a), above("Right_Tag", b), above("Out", c)])
    assert texts == ["XIC(Left_Tag)XIC(Right_Tag)OTE(Out);"]


@pytest.mark.parametrize("n", [1, 20, 120])
def test_many_symbols_on_one_rung_stay_in_x_order(n):
    dets = [sym("NO_Contact", 60 + 6 * W * i // 4, 100) for i in range(n)] + [sym("Output_Coil", 60 + 6 * W * n // 4, 100)]
    labels = [above(f"T{i}", d) for i, d in enumerate(dets)]
    texts, _, _ = run(dets, labels)
    assert texts[0] == "".join(f"XIC(T{i})" for i in range(n)) + f"OTE(T{n});"
