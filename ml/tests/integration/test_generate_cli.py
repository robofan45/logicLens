"""generate.py end to end: Ultralytics layout, determinism across runs, disjoint splits, safety."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ML_DIR = Path(__file__).resolve().parents[2]
COUNTS = {"train": 10, "val": 4, "test": 4}


def _run(out: Path, *extra: str, check: bool = True):
    cmd = [sys.executable, "-m", "generator.generate", "--out", str(out), "--n-train", str(COUNTS["train"]),
           "--n-val", str(COUNTS["val"]), "--n-test", str(COUNTS["test"]), "--seed", "5", "--preview", "4", *extra]
    return subprocess.run(cmd, cwd=ML_DIR, capture_output=True, text=True, timeout=600, check=check)


def _digest(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "report.json" and not p.name.startswith("preview") and p.name != "dataset.yaml":
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    a = tmp_path_factory.mktemp("gen_a")
    b = tmp_path_factory.mktemp("gen_b")
    _run(a)
    _run(b)
    return a, b


def test_layout_is_the_ultralytics_one(generated):
    root, _ = generated
    for split, n in COUNTS.items():
        images = sorted((root / "images" / split).iterdir())
        labels = sorted((root / "labels" / split).iterdir())
        metas = sorted((root / "meta" / split).iterdir())
        assert len(images) == len(labels) == len(metas) == n
        assert [p.stem for p in images] == [p.stem for p in labels] == [p.stem for p in metas]
        assert all(p.suffix in (".png", ".jpg") for p in images)
        assert (root / f"preview_{split}.png").is_file() and (root / f"preview_crops_{split}.png").is_file()
    report = json.loads((root / "report.json").read_text())
    assert report["counts"] == COUNTS


def test_dataset_yaml_loads_with_ultralytics_names(generated):
    yaml = pytest.importorskip("yaml")
    root, _ = generated
    cfg = yaml.safe_load((root / "dataset.yaml").read_text())
    contract = json.loads((ML_DIR.parent / "contract" / "classes.json").read_text())
    assert cfg["nc"] == contract["nc"] == 44
    assert [cfg["names"][i] for i in range(44)] == [c["name"] for c in contract["classes"]]
    assert Path(cfg["path"]) == root.resolve()


def test_generation_is_deterministic_across_runs(generated):
    a, b = generated
    da, db = _digest(a), _digest(b)
    assert da == db and len(da) == 3 * sum(COUNTS.values())


def test_splits_are_disjoint(generated):
    root, _ = generated
    programs, images = {}, {}
    for split in COUNTS:
        for meta_path in (root / "meta" / split).iterdir():
            meta = json.loads(meta_path.read_text())
            key = "\n".join(r["text"] for r in meta["rungs"])
            assert programs.setdefault(key, split) == split, f"program shared by {programs[key]} and {split}"
            img = (root / "images" / split / meta["image"]).read_bytes()
            h = hashlib.sha256(img).hexdigest()
            assert images.setdefault(h, split) == split


def test_labels_files_are_valid(generated):
    root, _ = generated
    for p in (root / "labels").rglob("*.txt"):
        for line in p.read_text().splitlines():
            cid, *vals = line.split()
            assert 0 <= int(cid) < 44 and int(cid) not in (38, 39)
            assert all(0.0 <= float(v) <= 1.0 for v in vals)


def test_refuses_a_non_empty_folder_without_overwrite(tmp_path):
    (tmp_path / "keep.txt").write_text("user data")
    res = _run(tmp_path, check=False)
    assert res.returncode != 0 and "not empty" in (res.stderr + res.stdout)
    assert (tmp_path / "keep.txt").read_text() == "user data"


def test_overwrite_only_touches_generated_files(tmp_path):
    _run(tmp_path)
    (tmp_path / "notes.md").write_text("mine")
    _run(tmp_path, "--overwrite")
    assert (tmp_path / "notes.md").read_text() == "mine"
    assert len(list((tmp_path / "images" / "train").iterdir())) == COUNTS["train"]


def test_rejects_bad_arguments(tmp_path):
    res = subprocess.run([sys.executable, "-m", "generator.generate", "--out", str(tmp_path / "x"), "--n-train", "-1"],
                         cwd=ML_DIR, capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
