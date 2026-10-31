"""The class table and parser come from contract/; every generated operand is a valid LLT tag."""
import random

import pytest

from generator import contract
from generator.contract import llt
from generator.tags import MAX_TAG_CHARS, PLATFORMS, TagSpace, split_slc_address


def test_class_table_is_the_contract_one():
    assert contract.NC == 44
    assert contract.NAMES[0] == "NO_Contact" and contract.NAMES[43] == "Power_Rail_Right"
    assert contract.SYMBOL_IDS == list(range(38))
    assert contract.DEPRECATED_IDS == {38, 39}
    assert (contract.BRANCH_START, contract.BRANCH_END, contract.RAIL_LEFT, contract.RAIL_RIGHT) == (40, 41, 42, 43)
    assert contract.EMITTED_IDS.isdisjoint(contract.DEPRECATED_IDS)


def test_instructions_without_a_class_are_known_and_never_sampled():
    # LIM, ONS, AFI, NOP are valid LLT but have no detector class in classes.json
    assert {"LIM", "ONS", "AFI", "NOP"} <= contract.UNLABELLED_MNEMONICS
    from generator.sampler import SUPPORTED
    for mnemonics in SUPPORTED.values():
        assert not (mnemonics & contract.UNLABELLED_MNEMONICS)


@pytest.mark.parametrize("platform", PLATFORMS)
@pytest.mark.parametrize("kind", ["din", "dout", "bit", "timer", "counter", "word", "label", "routine"])
def test_every_generated_operand_is_a_short_valid_tag(platform, kind):
    tags = TagSpace(platform, random.Random(f"{platform}:{kind}"))
    seen = set()
    for _ in range(120):
        tag = getattr(tags, kind)()
        op = llt.classify_operand(tag)
        assert op is not None and op.type == "tag", tag
        assert len(tag) <= MAX_TAG_CHARS, tag
        assert tag.lower() not in seen, f"duplicate {tag}"
        seen.add(tag.lower())


@pytest.mark.parametrize("platform", PLATFORMS)
def test_timer_and_counter_operands_have_contract_arity(platform):
    tags = TagSpace(platform, random.Random(platform))
    for m in ("TON", "TOF", "RTO", "TP"):
        if m == "TP" and platform.startswith("rockwell"):
            continue
        ops = tags.timer_operands(m, tags.timer())
        lo, hi, _ = llt.SPEC[m]
        assert lo <= len(ops) <= hi
        res = llt.parse_program(f"{m}({','.join(ops)});")
        assert res.ok, res.errors
        assert llt.timer_preset_ms(res.rungs[0].body.items[0]) > 0
    for m in ("CTU", "CTD"):
        ops = tags.counter_operands(m, tags.counter())
        assert llt.parse_program(f"{m}({','.join(ops)});").ok


@pytest.mark.parametrize("platform", PLATFORMS)
def test_members_are_valid_tags(platform):
    tags = TagSpace(platform, random.Random(1))
    for struct in (tags.timer(), tags.counter()):
        for which in ("DN", "TT", "EN", "ACC", "PRE"):
            tag = tags.member(struct, which)
            assert llt.classify_operand(tag).type == "tag", tag


@pytest.mark.parametrize("tag,expected", [
    ("I:1/3", ("I:1", "3")), ("O:2/15", ("O:2", "15")), ("B3:0/1", ("B3:0", "1")), ("B:0/1", ("B:0", "1")),
    ("N7:4/12", ("N7:4", "12")), ("S:1/15", ("S:1", "15")),
    ("T4:0/DN", None), ("C5:1/CU", None), ("T4:0.ACC", None), ("N7:0", None), ("Local:1:I.Data.0", None),
    ("%I0.1", None), ("Start_PB", None),
])
def test_rslogix500_split_display(tag, expected):
    assert split_slc_address(tag) == expected


def test_unknown_platform_is_rejected():
    with pytest.raises(ValueError):
        TagSpace("allen_bradley_plc5", random.Random(0))
