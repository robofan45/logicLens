"""Shared-vector and property tests for the Python LLT parser (gate 1)."""
import json
import pathlib
import random
import string

import pytest

from logiclens_ladder import (
    LIMITS, SPEC, classify_operand, iter_instructions, parse_program, print_program,
    time_literal_ms, timer_preset_ms,
)

CASES = json.loads((pathlib.Path(__file__).parent.parent / "ladder_cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_vector(case):
    res = parse_program(case["text"])
    assert res.ok == case["ok"], [e.to_dict() for e in res.errors]
    if "errors" in case:
        assert [e.code for e in res.errors] == case["errors"]
    if "error_lines" in case:
        assert [e.line for e in res.errors] == case["error_lines"]
    if "rungs" in case:
        got = [[i.mnemonic for i in iter_instructions(r.body)] for r in res.rungs]
        assert got == case["rungs"]
    if "numbers" in case:
        assert [r.number for r in res.rungs] == case["numbers"]
    if "comments" in case:
        assert [r.comment for r in res.rungs] == case["comments"]
    if "canonical" in case:
        assert print_program(res.rungs) == case["canonical"]
    if "timer_preset_ms" in case:
        got = [timer_preset_ms(i) for r in res.rungs for i in iter_instructions(r.body)
               if i.mnemonic in ("TON", "TOF", "RTO", "TP")]
        assert got == case["timer_preset_ms"]
    if "operand_types" in case:
        got = [o.type for r in res.rungs for i in iter_instructions(r.body) for o in i.operands]
        assert got == case["operand_types"]


def test_round_trip_of_every_valid_case():
    for case in CASES:
        res = parse_program(case["text"])
        again = parse_program(print_program(res.rungs))
        assert print_program(again.rungs) == print_program(res.rungs), case["name"]
        assert not again.errors, case["name"]


def test_instruction_ids_are_unique_and_ordered():
    res = parse_program("XIC(A)[XIC(B),XIC(C)]OTE(D);\nXIC(E)OTE(F);")
    ids = [i.id for r in res.rungs for i in iter_instructions(r.body)]
    assert ids == ["r0i0", "r0i1", "r0i2", "r0i3", "r1i0", "r1i1"]


def test_time_literals():
    assert time_literal_ms("T#5s") == 5000
    assert time_literal_ms("t#1h2m3s4ms") == 3_723_004
    assert time_literal_ms("TIME#1.5s") == 1500
    assert time_literal_ms("T#1_000ms") == 1000
    assert time_literal_ms("T#-2s") == -2000
    assert time_literal_ms("T#") is None
    assert time_literal_ms("T#5x") is None
    assert time_literal_ms("5s") is None


@pytest.mark.parametrize("raw,typ", [
    ("?", "unknown"), ("12", "number"), ("-1.5", "number"), (".5", "number"), ("2e3", "number"),
    ("16#ff", "number"), ("8#17", "number"), ("2#1010", "number"), ("T#5s", "time"),
    ("I:1/0", "tag"), ("%MW10", "tag"), ('"Motor Start"', "tag"), ("Data[3].2", "tag"),
])
def test_classify_operand(raw, typ):
    assert classify_operand(raw).type == typ


@pytest.mark.parametrize("raw", ["Start PB", "a+b", "x;y", "'q'", "16#XYZ", "2#102", 'bad"quote', "", "\x01"])
def test_invalid_operands(raw):
    assert classify_operand(raw) is None


def test_program_limit():
    res = parse_program("XIC(A)OTE(B);\n" * (LIMITS["program_chars"] // 14 + 1))
    assert [e.code for e in res.errors] == ["E_LIMIT"]
    assert res.rungs == []


def test_rung_count_limit():
    res = parse_program("XIC(A)OTE(B);\n" * (LIMITS["rungs"] + 5))
    assert len(res.rungs) == LIMITS["rungs"]
    assert res.errors[-1].code == "E_LIMIT"


def test_instruction_count_limit():
    res = parse_program("XIC(A)" * LIMITS["instructions"] + "OTE(B);")
    assert [e.code for e in res.errors] == ["E_LIMIT"]


def test_rung_length_limit():
    res = parse_program("XIC(A)" * 700 + "OTE(B);")
    assert [e.code for e in res.errors] == ["E_LIMIT"]


def test_non_string_input_does_not_raise():
    assert parse_program(None).errors[0].code == "E_SYNTAX"  # type: ignore[arg-type]


def test_error_columns_point_at_the_problem():
    res = parse_program("XIC(A)FOO(B)OTE(C);")
    assert (res.errors[0].line, res.errors[0].col) == (1, 7)
    res = parse_program("0003: XIC(A)FOO(B);")
    assert res.errors[0].col == 13


def _random_program(rng: random.Random, depth: int = 0) -> str:
    inputs = ["XIC", "XIO", "GRT", "ONS"]
    outputs = ["OTE", "OTL", "OTU", "TON", "CTU", "MOV"]
    def tag():
        return rng.choice(["A", "B", "Start_PB", "I:1/0", "%Q0.1", "T1.DN", "Data[2]"]) + str(rng.randint(0, 9))
    def ins(kind):
        m = rng.choice(kind)
        lo = SPEC[m][0]
        ops = [tag() if k == 0 else str(rng.randint(0, 999)) for k in range(lo)]
        if m == "MOV":
            ops = [str(rng.randint(0, 9)), tag()]
        return f"{m}({','.join(ops)})"
    def seq(d):
        out = []
        for _ in range(rng.randint(1, 3)):
            if d < 3 and rng.random() < 0.3:
                out.append("[" + ",".join(seq(d + 1) for _ in range(rng.randint(2, 3))) + "]")
            else:
                out.append(ins(inputs))
        return "".join(out)
    return seq(depth) + ins(outputs) + ";"


def test_fuzz_round_trip_random_programs():
    rng = random.Random(1234)
    for _ in range(2000):
        text = "\n".join(_random_program(rng) for _ in range(rng.randint(1, 4)))
        res = parse_program(text)
        assert res.ok, (text, [e.to_dict() for e in res.errors])
        assert print_program(res.rungs) == text


def test_fuzz_garbage_never_raises():
    rng = random.Random(99)
    alphabet = string.printable + "[](),;/#"
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        res = parse_program(text)
        assert isinstance(res.errors, list)


def test_non_ascii_unit_letters_are_rejected_not_raised():
    # U+017F (long s) case-folds to "s" under re.IGNORECASE without re.ASCII
    for raw in ["T#5\u017f", "T#5m\u017f", "TIME#1\u212a"]:
        assert classify_operand(raw) is None
    assert [e.code for e in parse_program("XIC(A)TON(T1,T#5\u017f);").errors] == ["E_SYNTAX"]


def test_ids_assigned_when_rung_limit_hits():
    res = parse_program("XIC(A)OTE(B);\n" * (LIMITS["rungs"] + 1))
    assert res.rungs[-1].body.items[0].id == f"r{LIMITS['rungs'] - 1}i0"
