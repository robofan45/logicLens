"""Thousands of sampled programs: valid, canonical, layout-friendly, deterministic."""
import random
from collections import Counter

import pytest

from generator.contract import ID_BY_MNEMONIC, llt
from generator.sampler import SUPPORTED, TEMPLATE_WEIGHTS, Br, Ins, ProgramSampler, depth, sample_program, walk
from generator.tags import PLATFORMS

N_PER_PLATFORM = 800


def _programs(platform):
    for i in range(N_PER_PLATFORM):
        yield sample_program(platform, random.Random(f"{platform}:{i}"), random.Random(i).randint(1, 9),
                             comment_rate=0.3)


def _is_out(item) -> bool:
    return any(i.role == "out" for i in walk([item]))


def _check_leg_order(items, top_level: bool):
    """Inputs first, then outputs; an output branch leg = inputs* outputs+."""
    k = next((i for i, it in enumerate(items) if _is_out(it)), len(items))
    for it in items[k:]:
        if isinstance(it, Ins):
            assert it.role == "out", f"input {it.text()} after an output"
        else:
            for leg in it.legs:
                assert leg, "empty leg in an output branch"
                kk = next(i for i, x in enumerate(leg) if _is_out(x))
                assert all(isinstance(x, Ins) and x.role == "out" for x in leg[kk:]), [x.text() for x in leg]
                assert not any(isinstance(x, Br) for x in leg), "no branches inside output branch legs"
    for it in items[:k]:
        if isinstance(it, Br):
            for j, leg in enumerate(it.legs):
                if not leg:
                    assert top_level and j == len(it.legs) - 1, "empty leg must be the last leg of a top-level branch"
                _check_leg_order(leg, top_level=False)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_sampled_programs_parse_and_round_trip(platform):
    for prog in _programs(platform):
        text = prog.text()
        res = llt.parse_program(text)
        assert res.ok, (text, res.errors)
        assert len(res.rungs) == len(prog.rungs)
        again = llt.parse_program(llt.print_program(res.rungs))
        assert [r.text for r in again.rungs] == [r.text for r in res.rungs]
        assert [r.comment for r in again.rungs] == [r.comment for r in res.rungs]
        # the sampler's own text is already canonical
        assert [r.text for r in res.rungs] == [r.text() for r in prog.rungs]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_sampled_programs_follow_the_layout_conventions(platform):
    for prog in _programs(platform):
        for rung in prog.rungs:
            mnemonics = {i.m for i in walk(rung.body)}
            assert mnemonics <= SUPPORTED[platform] <= set(ID_BY_MNEMONIC)
            assert depth(rung.body) <= 2
            assert any(i.role == "out" for i in walk(rung.body)), rung.text()
            _check_leg_order(rung.body, top_level=True)


def test_every_symbol_class_is_reachable_across_platforms():
    seen = Counter()
    for platform in PLATFORMS:
        for prog in _programs(platform):
            seen.update(i.m for r in prog.rungs for i in walk(r.body))
    seen["END"] += 1  # END is appended by the composer as the final rung (see test_layout)
    assert set(ID_BY_MNEMONIC) <= set(seen)


def test_templates_exist_for_every_weighted_name():
    for platform, weights in TEMPLATE_WEIGHTS.items():
        s = ProgramSampler(platform, random.Random(0))
        for name in weights:
            assert callable(getattr(s, f"_t_{name}"))


def test_sampling_is_deterministic_for_a_seed():
    a = sample_program("rockwell_slc", random.Random("x"), 8, 0.5).text()
    b = sample_program("rockwell_slc", random.Random("x"), 8, 0.5).text()
    c = sample_program("rockwell_slc", random.Random("y"), 8, 0.5).text()
    assert a == b and a != c
