"""Samples: valid YOLO labels, metadata consistent with the ground-truth program, determinism, splits."""
import hashlib
import io

import numpy as np
import pytest

from generator.contract import BRANCH_END, BRANCH_START, NC, RAIL_LEFT, RAIL_RIGHT, llt
from generator.dataset import (SPLITS, Sample, dataset_yaml, encode_image, make_sample, split_of, yolo_lines)

SEED = 7


@pytest.fixture(scope="module")
def clean_samples():
    return [make_sample(SEED, "train", i, aug="none") for i in range(14)]


@pytest.fixture(scope="module")
def aug_samples():
    return [make_sample(SEED, "train", i, aug=lvl) for i, lvl in zip(range(20, 30), ["light", "heavy"] * 5)]


def _branches(seq) -> int:
    return sum(1 + sum(_branches(leg) for leg in it.legs) for it in seq.items if isinstance(it, llt.Branch))


def _parse_lines(lines):
    out = []
    for line in lines:
        parts = line.split()
        assert len(parts) == 5
        out.append((int(parts[0]), *map(float, parts[1:])))
    return out


def test_labels_are_valid_yolo(clean_samples, aug_samples):
    for s in clean_samples + aug_samples:
        w, h = s.meta["size"]
        assert s.image.size == (w, h)
        for cid, cx, cy, bw, bh in _parse_lines(yolo_lines(s.labels, w, h)):
            assert 0 <= cid < NC and cid not in (38, 39)
            assert 0 < bw <= 1 and 0 < bh <= 1
            assert 0 <= cx - bw / 2 + 1e-6 and cx + bw / 2 <= 1 + 1e-6
            assert 0 <= cy - bh / 2 + 1e-6 and cy + bh / 2 <= 1 + 1e-6


def test_yolo_writer_refuses_wire_classes():
    with pytest.raises(ValueError):
        yolo_lines([(38, 0, 0, 10, 10)], 100, 100)
    with pytest.raises(ValueError):
        yolo_lines([(39, 0, 0, 10, 10)], 100, 100)


def test_symbol_labels_match_the_ground_truth_program(clean_samples):
    for s in clean_samples:
        res = llt.parse_program(s.meta["llt"])
        assert res.ok, res.errors
        gt = [ins for r in res.rungs for ins in llt.iter_instructions(r.body)]
        symbols = [lab for lab in s.labels if lab[0] < 38]
        assert len(symbols) == len(gt) == len(s.meta["instructions"])
        assert [r.text for r in res.rungs] == [r["text"] for r in s.meta["rungs"]]
        for ins, meta in zip(gt, s.meta["instructions"]):
            assert ins.mnemonic == meta["mnemonic"] and [o.raw for o in ins.operands] == meta["operands"]
            assert meta["visible"] and meta["box"] is not None
        n_branches = sum(1 for lab in s.labels if lab[0] == BRANCH_START)
        assert n_branches == sum(1 for lab in s.labels if lab[0] == BRANCH_END)
        assert n_branches == sum(_branches(r.body) for r in res.rungs)
        assert sum(1 for lab in s.labels if lab[0] == RAIL_LEFT) == 1
        assert sum(1 for lab in s.labels if lab[0] == RAIL_RIGHT) == 1


def test_structure_boxes_are_at_least_6px_wide(clean_samples, aug_samples):
    for s in clean_samples + aug_samples:
        for cid, x0, y0, x1, y1 in s.labels:
            if cid in (BRANCH_START, BRANCH_END, RAIL_LEFT, RAIL_RIGHT):
                assert x1 - x0 >= 6.0 - 1e-6


def test_augmented_metadata_is_consistent(aug_samples):
    for s in aug_samples:
        visible = [i for i in s.meta["instructions"] if i["visible"]]
        assert len([lab for lab in s.labels if lab[0] < 38]) == len(visible)
        w, h = s.meta["size"]
        for i in s.meta["instructions"]:
            if i["box"] is not None:
                x0, y0, x1, y1 = i["box"]
                assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
        assert s.meta["augment"]["level"] in ("light", "heavy")


def test_sample_is_deterministic_for_seed_split_index():
    a = make_sample(SEED, "val", 3)
    b = make_sample(SEED, "val", 3)
    c = make_sample(SEED, "val", 4)
    assert encode_image(a) == encode_image(b)
    assert a.labels == b.labels and a.meta == b.meta
    assert encode_image(a) != encode_image(c)


def test_split_is_a_function_of_the_program_text():
    seen = {}
    for split in SPLITS:
        for i in range(6):
            s = make_sample(SEED, split, i)
            texts = [r["text"] for r in s.meta["rungs"]]
            assert split_of(texts) == split
            key = "\n".join(texts)
            assert seen.setdefault(key, split) == split


def test_dataset_yaml_lists_the_44_names_in_order():
    from generator.contract import NAMES
    text = dataset_yaml("/data/x")
    lines = [l.strip() for l in text.splitlines()]
    assert "nc: 44" in lines
    names = [l.split(": ", 1)[1] for l in lines if l[:1].isdigit()]
    assert names == NAMES


def test_unknown_split_is_rejected():
    with pytest.raises(ValueError):
        make_sample(SEED, "holdout", 0)


def test_dataset_yaml_path_survives_yaml_special_characters():
    yaml = pytest.importorskip("yaml")
    for root in ("/data/run #3: test", "/data/a: b", "C:\\data\\x", "/data/'quoted' \"x\""):
        assert yaml.safe_load(dataset_yaml(root))["path"] == root


def test_canvas_and_supersampled_raster_are_memory_bounded():
    import random
    from generator.compose import MAX_CANVAS_SIDE, MAX_RASTER_SIDE, Composer
    from generator.styles import sample_style
    rng = random.Random(3)
    st = sample_style("tia", rng, "siemens_tia")
    st.u, st.ss = 30, 3
    c = Composer(st, "siemens_tia", rng, 4096)
    assert c.max_side() <= MAX_CANVAS_SIDE
    assert c.max_side() * st.ss <= MAX_RASTER_SIDE
