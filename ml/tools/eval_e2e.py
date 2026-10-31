"""End-to-end evaluation: image -> backend /api/analyze/parse -> LogicLens Ladder Text, scored
against the generator's ground truth (meta/<split>/*.json "llt").

This is the number that matters to a user: not box mAP, but whether the recognised program is
right. Runs against a live backend (loopback only), so it also exercises the API.

    python ml/tools/eval_e2e.py --url http://127.0.0.1:8000 --split test --limit 120

Metrics (rungs aligned by position):
  program_exact   every rung's canonical text equals the ground truth
  rung_exact      share of ground-truth rungs reproduced exactly
  mnemonic P/R/F1 per-rung multiset overlap of instruction mnemonics
  operand_acc     operands equal, over instructions whose mnemonic matches at the same position
  unknown_rate    share of predicted operands that came back as '?'
"""
from __future__ import annotations

import argparse
import collections
import json
import mimetypes
import pathlib
import sys
import time
import urllib.parse
import urllib.request
import uuid

ML = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML.parent / "contract" / "python"))
from logiclens_ladder import iter_instructions, parse_program  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def post_image(url: str, path: pathlib.Path, timeout: float = 120.0) -> dict:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url.rstrip("/") + "/api/analyze/parse", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310 - http(s) to a loopback host only, checked in main()
        return json.loads(r.read())


def rung_view(text: str):
    res = parse_program(text)
    return [([i.mnemonic for i in iter_instructions(r.body)], [[o.raw for o in i.operands] for i in iter_instructions(r.body)], r.text)
            for r in res.rungs]


def score(gt_text: str, pred_rungs: list[str]) -> dict:
    gt = rung_view(gt_text)
    pred = rung_view("\n".join(pred_rungs))
    out = collections.Counter()
    out["gt_rungs"] = len(gt)
    out["pred_rungs"] = len(pred)
    for k in range(max(len(gt), len(pred))):
        g = gt[k] if k < len(gt) else ([], [], None)
        p = pred[k] if k < len(pred) else ([], [], None)
        if g[2] is not None and g[2] == p[2]:
            out["rung_exact"] += 1
        gm, pm = collections.Counter(g[0]), collections.Counter(p[0])
        out["mn_tp"] += sum((gm & pm).values())
        out["mn_gt"] += sum(gm.values())
        out["mn_pred"] += sum(pm.values())
        for j in range(min(len(g[0]), len(p[0]))):
            if g[0][j] != p[0][j]:
                continue
            for a, b in zip(g[1][j], p[1][j]):
                out["ops"] += 1
                out["ops_ok"] += int(a == b)
        out["pred_ops"] += sum(len(ops) for ops in p[1])
        out["pred_unknown"] += sum(o == "?" for ops in p[1] for o in ops)
    out["program_exact"] = int(len(gt) == len(pred) and out["rung_exact"] == len(gt))
    return out


def summarise(c: collections.Counter, n: int) -> dict:
    p = c["mn_tp"] / c["mn_pred"] if c["mn_pred"] else 0.0
    r = c["mn_tp"] / c["mn_gt"] if c["mn_gt"] else 0.0
    return {
        "images": n,
        "program_exact": round(c["program_exact"] / n, 4) if n else 0.0,
        "rung_exact": round(c["rung_exact"] / c["gt_rungs"], 4) if c["gt_rungs"] else 0.0,
        "mnemonic_precision": round(p, 4),
        "mnemonic_recall": round(r, 4),
        "mnemonic_f1": round(2 * p * r / (p + r), 4) if p + r else 0.0,
        "operand_acc": round(c["ops_ok"] / c["ops"], 4) if c["ops"] else 0.0,
        "unknown_rate": round(c["pred_unknown"] / c["pred_ops"], 4) if c["pred_ops"] else 0.0,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--data", type=pathlib.Path, default=ML / "data" / "v2")
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--out", type=pathlib.Path, default=ML / "reports" / "e2e_eval.json")
    a = ap.parse_args(argv)
    host = urllib.parse.urlparse(a.url).hostname or ""
    if host not in LOOPBACK:
        print(f"refusing to send images to {host!r}: loopback only", file=sys.stderr)
        return 2
    metas = sorted((a.data / "meta" / a.split).glob("*.json"))
    if a.limit:
        metas = metas[: a.limit]
    total = collections.Counter()
    by_style: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    by_aug: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    n_style: collections.Counter = collections.Counter()
    n_aug: collections.Counter = collections.Counter()
    failures, t0, worst = 0, time.time(), []
    for m in metas:
        meta = json.loads(m.read_text())
        img = a.data / "images" / a.split / meta["image"]
        try:
            res = post_image(a.url, img)
            pred = [r["text"] for r in res.get("rungs", [])]
        except Exception as e:  # noqa: BLE001 - count and continue
            failures += 1
            pred = []
            print(f"{img.name}: request failed: {e}", file=sys.stderr)
        s = score(meta["llt"], pred)
        aug = meta.get("augment", {}).get("level", "?") if isinstance(meta.get("augment"), dict) else "?"
        total.update(s)
        by_style[meta.get("style", "?")].update(s)
        by_aug[aug].update(s)
        n_style[meta.get("style", "?")] += 1
        n_aug[aug] += 1
        if not s["program_exact"]:
            worst.append({"image": img.name, "style": meta.get("style"), "augment": aug, "gt": meta["llt"], "pred": "\n".join(pred)})
    report = {
        "split": a.split,
        "elapsed_s": round(time.time() - t0, 1),
        "request_failures": failures,
        "overall": summarise(total, len(metas)),
        "by_style": {k: summarise(v, n_style[k]) for k, v in sorted(by_style.items())},
        "by_augmentation": {k: summarise(v, n_aug[k]) for k, v in sorted(by_aug.items())},
        "examples_wrong": worst[:15],
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in ("overall", "by_style", "by_augmentation", "elapsed_s", "request_failures")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
