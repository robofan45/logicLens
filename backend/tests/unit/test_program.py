import json

import jsonschema
import pytest

from app.errors import ApiError
from app.program import ElementDraft, RungDraft, finalize_rungs, guess_platform, program_from_text
from app.vendor.logiclens_ladder import parse_program
from tests.helpers import REPO, SAMPLE_TRUTH

SCHEMA_PATH = REPO / "contract" / "program.schema.json"


@pytest.fixture(scope="module")
def schema():
    if not SCHEMA_PATH.exists():
        pytest.skip("contract/program.schema.json not available")
    return json.loads(SCHEMA_PATH.read_text())


def test_valid_rungs_are_canonicalised_and_elements_aligned():
    warnings = []
    drafts = [RungDraft(text="xic(A) [xic(B), xio(C)] ote(D)", elements=[
        ElementDraft("XIC", ["A"], [1, 2, 3, 4], 90),
        ElementDraft("XIC", ["B"], [5, 6, 7, 8], 80),
        ElementDraft("XIO", ["C"], None, 70),
        ElementDraft("OTE", ["D"], [9, 9, 10, 10], 60),
    ])]
    rungs = finalize_rungs(drafts, warnings)
    assert warnings == []
    assert rungs[0].text == "XIC(A)[XIC(B),XIO(C)]OTE(D);"
    assert [e.mnemonic for e in rungs[0].elements] == ["XIC", "XIC", "XIO", "OTE"]
    assert [e.index for e in rungs[0].elements] == [0, 1, 2, 3]
    assert rungs[0].elements[1].bbox == [5, 6, 7, 8]
    assert rungs[0].elements[3].operands == ["D"]


def test_invalid_rung_is_dropped_with_a_warning_and_numbering_is_kept():
    warnings = []
    drafts = [RungDraft(text="XIC(A)OTE(B);"), RungDraft(text="XIC(A)FOO(B);"), RungDraft(text="XIO(C)OTE(D);")]
    rungs = finalize_rungs(drafts, warnings)
    assert [r.text for r in rungs] == ["XIC(A)OTE(B);", "XIO(C)OTE(D);"]
    assert [r.number for r in rungs] == [0, 2]
    assert len(warnings) == 1 and "E_UNKNOWN_MNEMONIC" in warnings[0] and "Rung 1" in warnings[0]


def test_two_rungs_in_one_draft_are_rejected():
    warnings = []
    assert finalize_rungs([RungDraft(text="XIC(A)OTE(B);XIC(C)OTE(D);")], warnings) == []
    assert "exactly one rung" in warnings[0]


def test_element_overlay_with_wrong_mnemonic_is_not_attached():
    warnings = []
    rungs = finalize_rungs([RungDraft(text="XIC(A)OTE(B);", elements=[ElementDraft("XIO", ["A"], [1, 1, 2, 2], 50)])],
                           warnings)
    assert rungs[0].elements[0].bbox is None
    assert rungs[0].elements[1].bbox is None


def test_aliases_count_as_the_same_mnemonic_for_overlay_alignment():
    rungs = finalize_rungs([RungDraft(text="NO(A)COIL(B);", elements=[ElementDraft("NO", ["A"], [1, 1, 2, 2], 50)])],
                           [])
    assert rungs[0].elements[0].bbox == [1, 1, 2, 2]


def test_non_increasing_model_numbers_are_renumbered():
    warnings = []
    rungs = finalize_rungs([RungDraft(text="XIC(A)OTE(B);", number=5), RungDraft(text="XIC(A)OTE(C);", number=5)],
                           warnings)
    assert [r.number for r in rungs] == [5, 6]
    assert any("renumbered" in w for w in warnings)


def test_program_from_text_matches_schema_and_parser(schema):
    text = "\n".join(SAMPLE_TRUTH)
    program = program_from_text(text, None).to_json()
    jsonschema.validate(program, schema)
    assert program["source"] == "text" and program["engine"]["name"] == "text"
    assert [r["text"] for r in program["rungs"]] == SAMPLE_TRUTH
    assert program["platform"] == "rockwell_slc"
    reparsed = parse_program("\n".join(r["text"] for r in program["rungs"]))
    assert reparsed.ok


def test_program_from_text_keeps_comments_and_labels():
    program = program_from_text("// start motor\n0007: XIC(Start)OTE(Motor);", "rockwell_logix").to_json()
    rung = program["rungs"][0]
    assert rung["number"] == 7 and rung["comment"] == "start motor"
    assert program["platform"] == "rockwell_logix" and program["platform_confidence"] == 100


def test_program_from_text_syntax_error_is_422_with_parser_details():
    with pytest.raises(ApiError) as exc:
        program_from_text("XIC(A)OTE(B);\nXIC(A]OTE(B);", None)
    err = exc.value
    assert (err.status, err.code) == (422, "E_LADDER_SYNTAX")
    assert err.details and err.details[0]["code"] == "E_UNBALANCED" and err.details[0]["line"] == 2


def test_program_from_empty_text_is_422():
    with pytest.raises(ApiError) as exc:
        program_from_text("  \n// only a comment\n", None)
    assert exc.value.code == "E_LADDER_SYNTAX"


@pytest.mark.parametrize("text,platform", [
    ("XIC(I:1/1)XIC(B3:0/1)OTE(O:2/1);", "rockwell_slc"),
    ("XIC(T4:0.DN)TON(T4:0,0.01,500,0);", "rockwell_slc"),
    ("XIC(Local:1:I.Data.0)OTE(Local:2:O.Data.1);", "rockwell_logix"),
    ("XIC(%I0.0)XIO(%I0.1)OTE(%Q0.0);", "siemens_tia"),
    ("XIC(%IX0.0)OTE(%QX0.0);", "generic_iec"),
    ("XIC(X0)XIO(X1)OTE(Y0);", "mitsubishi"),
    ("XIC(Start_PB)OTE(Motor);", "unknown"),
])
def test_platform_guess_from_addressing_style(text, platform):
    guessed, confidence = guess_platform(parse_program(text).rungs)
    assert guessed == platform
    assert (confidence is None) == (platform == "unknown")
    if confidence is not None:
        assert 0 < confidence <= 95
