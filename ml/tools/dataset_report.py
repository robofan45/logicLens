"""Turn a generated dataset's report.json into a Markdown summary (class histogram per split).

    python tools/dataset_report.py data/v2/report.json > reports/dataset_report.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def render(report: dict) -> str:
    hist = report["class_histogram"]
    splits = [s for s in ("train", "val", "test") if s in hist]
    lines = ["# Dataset v2 summary", "",
             f"seed {report['seed']}, imgsz hint {report['imgsz_hint']}, generated in {report.get('seconds', '?')} s", "",
             "| | " + " | ".join(splits) + " |", "|---|" + "---|" * len(splits),
             "| images | " + " | ".join(str(report["counts"][s]) for s in splits) + " |",
             "| labels | " + " | ".join(str(sum(hist[s].values())) for s in splits) + " |",
             "| long side px (min/median/max) | " + " | ".join(
                 "{min}/{median}/{max}".format(**report["image_size"][s]) for s in splits) + " |",
             "| smallest contact at imgsz, px (min/p05/median) | " + " | ".join(
                 "{min}/{p05}/{median}".format(**report["symbol_px_at_imgsz"][s]) for s in splits) + " |",
             "", "## Styles, platforms, augmentation (train)", "",
             f"styles: {json.dumps(report['styles']['train'])}", "",
             f"platforms: {json.dumps(report['platforms']['train'])}", "",
             f"augmentation: {json.dumps(report['augment']['train'])}", "",
             "## Class histogram", "", "| id | class | " + " | ".join(splits) + " |", "|---|---|" + "---|" * len(splits)]
    names = list(hist[splits[0]].keys())
    for i, n in enumerate(names):
        lines.append(f"| {i} | {n} | " + " | ".join(str(hist[s][n]) for s in splits) + " |")
    sym = {n: hist["train"][n] for n in names[:38]}
    lo = min(sym, key=sym.get)
    lines += ["", f"Rarest symbol class in train: **{lo}** ({sym[lo]}). Classes 38/39 (wires) are never labelled."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(json.loads(Path(sys.argv[1]).read_text())), end="")
