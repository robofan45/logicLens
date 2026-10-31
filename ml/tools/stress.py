"""Gate 6 for the ML build: thousands of inputs through the generator and the deployed model.

    nice -n 15 python tools/stress.py --model models/logiclens-yolov8n.onnx --plans 4000 --renders 200 \
        --inferences 1000 --threads-max 8

1. generator fuzz  - thousands of seeds through sampler + layout (every program must parse; no
                     exception), a few hundred full renders with timing and peak RSS;
2. inference load  - the backend's exact pipeline (letterbox, ONNX, decode) on real test images and
                     hostile inputs (tiny, huge, 20:1 strips, grayscale, RGBA, pure noise); checks for
                     crashes, non-finite boxes, boxes outside the image, memory growth;
3. concurrency     - 1..N threads sharing one InferenceSession (what a backend worker does): throughput
                     and p95 latency per step, and the step where adding users stops adding throughput.
"""
from __future__ import annotations

import argparse
import json
import random
import resource
import statistics
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

ML_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ML_DIR))
sys.path.insert(0, str(ML_DIR / "train"))


def rss_mb() -> float:
    """Peak RSS of this process (MB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def current_rss_mb() -> float:
    """Current RSS (MB); falls back to the peak where /proc is unavailable."""
    try:
        import os
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20
    except (OSError, ValueError, IndexError):
        return rss_mb()


def leak_check(model: Path, test_dir: Path, n: int = 600) -> dict:
    """Current RSS sampled every 100 inferences on ordinary images: should stay flat."""
    from onnx_infer import OnnxDetector
    det = OnnxDetector(model, threads=1)
    images = [Image.open(p).convert("RGB") for p in sorted(test_dir.iterdir())[:20]]
    samples = []
    for i in range(n):
        det(images[i % len(images)])
        if i % 100 == 99:
            samples.append(round(current_rss_mb(), 1))
    return {"inferences": n, "rss_mb_every_100": samples,
            "drift_after_warmup_mb": round(samples[-1] - samples[min(1, len(samples) - 1)], 1)}


def generator_fuzz(n_plans: int, n_renders: int) -> dict:
    from generator.contract import llt
    from generator.dataset import make_sample, plan_sample
    t0 = time.time()
    errors, rungs = [], 0
    for i in range(n_plans):
        try:
            _, _, plan = plan_sample(1000 + i, "train", i)
            res = llt.parse_program(plan.program)
            if not res.ok:
                errors.append((i, str(res.errors[0])))
            rungs += len(plan.rungs)
        except Exception as exc:  # the point of a fuzz run is to collect, not to stop
            errors.append((i, repr(exc)))
    plan_s = time.time() - t0
    times = []
    for i in range(n_renders):
        t = time.time()
        try:
            make_sample(2000 + i, "train", i)
        except Exception as exc:
            errors.append(("render", i, repr(exc)))
        times.append(time.time() - t)
    times.sort()
    return {"plans": n_plans, "plan_seconds": round(plan_s, 1), "rungs": rungs, "renders": n_renders,
            "render_p50_s": round(times[len(times) // 2], 3) if times else None,
            "render_p95_s": round(times[int(len(times) * 0.95) - 1], 3) if times else None,
            "errors": errors[:20], "n_errors": len(errors), "peak_rss_mb": round(rss_mb(), 1)}


def hostile_inputs(rng: random.Random, test_images):
    yield "tiny", Image.new("RGB", (8, 8), "white")
    yield "1px", Image.new("RGB", (1, 1), "black")
    yield "strip_h", Image.new("RGB", (4000, 200), "white")
    yield "strip_v", Image.new("RGB", (150, 3000), "white")
    yield "huge", Image.new("RGB", (4000, 3000), "white")
    yield "gray", Image.open(rng.choice(test_images)).convert("L")
    yield "rgba", Image.open(rng.choice(test_images)).convert("RGBA")
    yield "noise", Image.fromarray(np.random.default_rng(rng.getrandbits(32)).integers(0, 256, (600, 900, 3), dtype=np.uint8))
    yield "black", Image.new("RGB", (900, 500), "black")


def inference_load(model: Path, test_dir: Path, n: int) -> dict:
    from onnx_infer import OnnxDetector
    det = OnnxDetector(model, threads=1)
    rng = random.Random(0)  # nosec B311 - picks stress inputs, not security
    images = sorted(test_dir.iterdir())
    lat, bad, crashes = [], [], []
    rss0 = current_rss_mb()
    inputs = list(hostile_inputs(rng, images))
    for i in range(n):
        if i < len(inputs):
            name, img = inputs[i]
        else:
            p = images[i % len(images)]
            img = Image.open(p)
            name = p.name
            if rng.random() < 0.3:  # random crop / rescale of a real test image
                w, h = img.size
                x0, y0 = rng.randint(0, w // 3), rng.randint(0, h // 3)
                img = img.crop((x0, y0, rng.randint(x0 + 16, w), rng.randint(y0 + 16, h)))
                s = rng.uniform(0.3, 2.5)
                img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))
        t = time.perf_counter()
        try:
            dets = det(img.convert("RGB"))
        except Exception as exc:
            crashes.append((name, repr(exc)))
            continue
        lat.append((time.perf_counter() - t) * 1000)
        w, h = img.size
        for c, p_, b in dets:
            if not (np.isfinite(b).all() and 0 <= b[0] <= b[2] <= w and 0 <= b[1] <= b[3] <= h and 0 <= p_ <= 1):
                bad.append((name, c, p_, b))
    lat.sort()
    return {"inferences": n, "crashes": crashes, "bad_boxes": bad[:10], "n_bad_boxes": len(bad),
            "p50_ms": round(lat[len(lat) // 2], 1), "p95_ms": round(lat[int(len(lat) * 0.95) - 1], 1),
            "max_ms": round(lat[-1], 1), "current_rss_change_mb": round(current_rss_mb() - rss0, 1),
            "peak_rss_mb": round(rss_mb(), 1)}


def concurrency(model: Path, test_dir: Path, threads_max: int, per_step_s: float) -> dict:
    from onnx_infer import OnnxDetector
    det = OnnxDetector(model, threads=1)  # one session per worker process, shared by its threads
    images = [Image.open(p).convert("RGB") for p in sorted(test_dir.iterdir())[:24]]
    steps = []
    users = 1
    while users <= threads_max:
        lat, stop = [], time.time() + per_step_s
        lock = threading.Lock()

        def user(k):
            i = k
            while time.time() < stop:
                t = time.perf_counter()
                det(images[i % len(images)])
                with lock:
                    lat.append((time.perf_counter() - t) * 1000)
                i += users

        ts = [threading.Thread(target=user, args=(k,)) for k in range(users)]
        t0 = time.time()
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        elapsed = time.time() - t0
        lat.sort()
        steps.append({"users": users, "requests": len(lat), "throughput_rps": round(len(lat) / elapsed, 2),
                      "p50_ms": round(lat[len(lat) // 2], 1), "p95_ms": round(lat[max(0, int(len(lat) * 0.95) - 1)], 1)})
        users *= 2
    best = max(s["throughput_rps"] for s in steps)
    knee = next((s["users"] for s in steps if s["throughput_rps"] >= 0.9 * best), steps[-1]["users"])
    return {"steps": steps, "saturates_at_users": knee, "max_throughput_rps": best}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", type=Path, default=ML_DIR / "models" / "logiclens-yolov8n.onnx")
    ap.add_argument("--test-dir", type=Path, default=ML_DIR / "data" / "v2" / "images" / "test")
    ap.add_argument("--plans", type=int, default=4000)
    ap.add_argument("--renders", type=int, default=200)
    ap.add_argument("--inferences", type=int, default=1000)
    ap.add_argument("--threads-max", type=int, default=8)
    ap.add_argument("--step-seconds", type=float, default=20.0)
    ap.add_argument("--out", type=Path, default=ML_DIR / "reports" / "stress.json")
    a = ap.parse_args(argv)
    report = {"generator": generator_fuzz(a.plans, a.renders)}
    print(json.dumps(report["generator"], indent=1), flush=True)
    if a.model.is_file():
        report["inference"] = inference_load(a.model, a.test_dir, a.inferences)
        print(json.dumps(report["inference"], indent=1), flush=True)
        report["leak_check"] = leak_check(a.model, a.test_dir)
        print(json.dumps(report["leak_check"], indent=1), flush=True)
        report["concurrency"] = concurrency(a.model, a.test_dir, a.threads_max, a.step_seconds)
        print(json.dumps(report["concurrency"], indent=1), flush=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
