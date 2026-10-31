# LogicLens ml/ — synthetic ladder data and the symbol detector

Everything that turns ladder-diagram *images* into detections the backend can assemble:

```
ml/
  generator/            synthetic dataset v2 (pure Python: Pillow, NumPy, OpenCV)
    contract.py           imports contract/classes.json and the reference LLT parser (never copied)
    tags.py               operand styles: rockwell_slc, rockwell_logix, siemens_tia, generic_iec
    sampler.py            random but realistic LLT programs (templates, coverage-tuned weights)
    styles.py             6 visual families: rslogix500, studio5000, tia, iec, printed, dark
    compose.py            contract section 6 layout + drawing primitives + annotations
    raster.py             supersampled rasteriser; every label box = bbox of that element's own ink
    augment.py            perspective/rotation/scale + lighting, moire, blur, noise, JPEG; exact box transform
    dataset.py            one sample end to end, YOLO lines, metadata, split hashing
    preview.py            contact sheets for visual QA
    generate.py           the CLI
  train/
    train.py              Ultralytics training with a wall-clock budget (hash-pinned pretrained weights)
    export.py             ONNX export + contract verification (shape, opset, no NMS, torch parity)
    evaluate.py           mAP per class on the test split + CPU latency with the backend pipeline
    predict_sample.py     the real RSLogix 500 screenshot -> reports/sample_prediction.png/.json
    onnx_infer.py         the backend's letterbox/decode (imported from backend/ when available)
  tools/stress.py       gate 6: generator fuzz, inference load with hostile inputs, concurrency ramp
  models/               logiclens-yolov8n.onnx, model_card.md, metrics.json, *.export.json
  reports/              sample_prediction.png/.json, stress.json, dataset_report.md
  tests/unit, tests/integration   pytest (markers by folder: pytest -m unit / -m integration)
  legacy/               the v1 generator and data (kept for reference; do not train on it)
```

## Quick start

```bash
cd ml
pip install -r requirements.txt                       # generator, tests, export, evaluation
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # CPU training only
python -m pytest -m unit                               # ~1 min
python -m pytest -m integration                        # ~1 min, includes the backend assembler conformance test

# dataset (deterministic for a seed; --workers N only changes speed)
python -m generator.generate --out data/v2 --n-train 2000 --n-val 300 --n-test 300 --seed 1 --imgsz-hint 736

# CPU pilot (what produced models/logiclens-yolov8n.onnx); weights: ultralytics/assets v8.3.0 yolov8n.pt
mkdir -p train/weights && curl -L -o train/weights/yolov8n.pt \
  https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt     # SHA-256 is pinned in train.py
nice -n 15 python train/train.py --data data/v2/dataset.yaml --hours 1.6 --imgsz 736 --batch 8 --threads 2 --name pilot
python train/export.py --weights runs/pilot/weights/best.pt --imgsz 736 --out models/logiclens-yolov8n.onnx
python train/evaluate.py --model models/logiclens-yolov8n.onnx --data data/v2/dataset.yaml
python train/predict_sample.py --model models/logiclens-yolov8n.onnx
```

## Pilot results (details in `models/model_card.md`)

| | |
|---|---|
| data | 2000 / 300 / 300 synthetic images, 34,682 training labels, rarest symbol class 194 instances |
| training | YOLOv8n from COCO, 736 px, 2 CPU threads, 1.6 h budget -> 6.3 epochs (97 min wall) |
| test split (synthetic) | P 0.844, R 0.859, **mAP50 0.891, mAP50-95 0.821**; contacts/coils/END/JSR/MCR ~0.99 mAP50; weakest: rails, XOR, GEQ, LEQ, AND |
| latency (CPU, backend pipeline) | p50 135 ms (1 thread), 96 ms (2 threads) |
| real RSLogix 500 screenshot | 14/14 objects detected with the right class, 0 false positives; with the backend assembler + Tesseract all 3 rungs exact (the backend's model integration test passes) |

## The dataset (v2)

**Programs.** `sampler.py` draws rungs from templates: motor seal-in with stop and overload,
interlock chains, OR logic, TON/TOF/RTO/TP with their done bit used in later rungs, CTU/CTD/CTUD
with RES, compares (EQU NEQ GRT LES GEQ LEQ), ADD/SUB/MUL/DIV/MOV, AND/OR/XOR/NOT, OSR/OSF, IEC
edge contacts P/N, OTL/OTU pairs, NCOIL (IEC), parallel output branches, nested branches (depth
<= 2, nested in the first, a middle or the last leg), JMP/LBL, JSR, MCR zones and an END rung.
All 38 symbol classes are covered; weights are tuned so each has >= ~190 instances per 2000
training images (`report.json` has the real histogram). Every ground-truth program is parsed by
the contract parser and round-trips. LIM, ONS, AFI and NOP are valid LLT but have **no class** in
classes.json, so they are never generated (a drawn but unlabelled instruction would teach the
detector to ignore it).

**Platforms (operand styles).** `rockwell_slc` (I:1/0, O:2/3, B3:0/1, T4:0/DN, N7:0, F8:1,
S:1/15, labels Q2:n, subroutines U:n), `rockwell_logix` (Start_PB, Local:1:I.Data.0,
Fill_Timer.DN, arrays), `siemens_tia` (%I0.0, %Q0.0, %M10.0, %MW20, %DB1.DBW2, quoted symbols,
#locals, T#5s presets), `generic_iec` (START_PB, T_FILL.Q, T#5s). Tags are <= 16 characters so
the text above a contact stays inside the window the backend OCR reads.

**Looks.** rslogix500 (matches `samples/ladder_logic_program_PLC1.webp`: purple strokes, `] [`
contacts, chevron coils, serif addresses split `I:1` above / `1` below, rung numbers 0000, green
energized bars touching the brackets, EN/DN stubs on timers), studio5000 (black, tag names and
descriptions above, round coils, grey number gutter), tia (`| |` contacts, network header bands,
box headers, TONR/MOVE/INV titles), iec (CODESYS-like colours), printed (paper, page frame,
serif or mono) and dark IDE themes. Fonts, stroke widths (1-3 px), symbol heights (14-30 px),
spacing, comments, descriptions, highlight rates and supersampling (1x aliased GDI look to 3x
anti-aliased) are randomised per image.

**Layout = contract section 6** (`compose.py`): rails full height, rung number left of the left
rail; inputs left to right from the left rail, outputs right-aligned to the right rail; a branch
draws leg 0 on the current row and each further leg on its own row below (nested legs directly
under their parent leg), joined by a vertical connector at each end; operands centred above
contacts/coils (RSLogix 500: split numeric bit addresses; `T4:0/DN` stays whole); box
instructions have their title row centred on the rung line (so the assembler's anchor
`y1 + 0.5 * contact_height` lands on the line) and print mnemonic, optional description, and
`Label value` rows (`Timer T4:0`, `Time Base 0.01`, `Preset 500<`, `Source A N7:0`, `Dest ...`,
`Storage Bit`, `Output Bit`, `Routine Name`) using exactly the label vocabulary of
`backend/app/engines/ocr.parse_box_text`.

**Labels.** One YOLO line per instruction (tight box around the symbol's own ink: brackets,
parentheses with their letter, or the box rectangle; operand text is never inside a contact or
coil box), one per branch connector (`Branch_Start` 40 left, `Branch_End` 41 right, >= 6 px wide,
spanning the first to the last leg) and one per rail (42/43, >= 7 px wide). Classes 38/39
(wires) are never written. Boxes come from rasterising each element alone into a mask aligned to
the supersampling grid (`raster.py`), so they are exact, not estimated.

**Metadata** (`meta/{split}/{stem}.json`): `llt` (canonical `print_program`, with rung comments),
`rungs[]` (text, comment, displayed number, band box, instruction indices), `instructions[]` in
text order (mnemonic, class, operands, symbol box, visibility, row, every drawn text item with its
role - operand, bit, desc, box_title, box_desc, box_row, box_value, stub - string and box),
`structures[]`, `decor[]` (rung numbers, comments, headers), `style`, `platform`, `augment`.
That is enough to run the backend assembler on ground-truth boxes, without a model (see
`tests/integration/test_backend_assembler.py`).

**Augmentation** (75 % of images; 40 % light, 25 % heavy): scale 0.75-1.3, rotation <= 2 deg,
mild perspective, padding/bezel, uneven lighting, brightness/contrast/gamma, colour cast,
screen-photo moire (with LCD sub-pixel stripes), blur, Gaussian noise, JPEG 35-95. Each
element's ink hull goes through the same homography (pixel-edge coordinates, OpenCV's half-pixel
convention handled), the AABB is clipped, boxes keeping < 40 % of their area are dropped and
marked `visible: false` in the metadata.

**Determinism and splits.** A sample depends only on `(seed, split, index)`. The split of a sample
is a hash of its ground-truth rung texts (80/10/10 buckets); candidates that hash to another split
are rejected, so no program can appear in two splits (the v1 data had val == train).

**Canvas size vs. training size.** `--imgsz-hint` (default 736) bounds the canvas so that the
smallest contact/coil is >= 14 px after letterboxing to that size; 25 % of images use a smaller
canvas (larger symbols). The real sample (892 x 508, 17 px contacts) lands at 14 px at 736.

## Files the backend uses

| backend | ml |
|---|---|
| `LOGICLENS_YOLO_ONNX` -> `engines/yolo_onnx.py` | `models/logiclens-yolov8n.onnx`: input `images` [1, 3, 736, 736] float32 RGB / 255, letterboxed with 114 padding; output `output0` [1, 48, 11109] = cx, cy, w, h (letterboxed px) + 44 sigmoid class scores; no NMS in the graph (the backend does class-wise NMS). |
| class order (`engines/base.py`, vendored classes.json) | `dataset.yaml` names are read from `contract/classes.json`; `export.py` refuses a checkpoint whose names differ. |
| `engines/assembler.py` | renders follow contract section 6 (above); `tests/integration/test_backend_assembler.py` proves the assembler rebuilds the ground truth from ground-truth boxes. |
| `tests/integration/test_redis_and_model.py` | picks up every `ml/models/*.onnx` automatically - keep exactly one model there. |

Settings: the backend reads the input size from the model (static 736), so `LOGICLENS_YOLO_IMGSZ`
is not needed; `yolo_conf=0.25`, `yolo_iou=0.45` are reasonable for this model.

### What the assembler author should know (found by the conformance test)

With ground-truth boxes and ideal OCR the assembler rebuilds every program that avoids the three
cases below exactly; each case is pinned by a strict xfail that will start failing once fixed:

1. `ocr.normalize_operand` strips double quotes, so TIA symbols `"Start_PB"` come back as `Start_PB`.
2. `parse_box_text` returns `?` for an optional trailing slot that is not drawn: IEC `TON(T1,T#5s)`
   and `CTU(C1,10)` come back as `TON(T1,T#5s,?)` / `CTU(C1,10,?)`. Suggest: stop at the minimum
   arity when the remaining slots were never seen.
3. `_attach_loose_rows` merges an unconditional output-only rung (`JSR(U:3);`, `MOV(0,N7:1);`, a
   centred `END();`) drawn under another rung's outputs into that rung as a connector-less parallel
   output leg. Real programs have many such rungs. Suggest: check for a wire from the left rail at
   that row (pixel run), or OCR the rung number left of the rail, before inferring a leg.

Conventions I had to interpret: RSLogix 500 splits only numeric bit addresses (`T4:0/DN` is drawn
whole, because `join_split_address` only joins digits); JSR rows use `Routine Name` (RSLogix 500
prints `SBR File Number`, which `parse_box_text` does not know); END is drawn as a coil-like
`(END)`, centred on its rung in Rockwell styles; RES and JMP are coil-style, LBL contact-style,
MCR/END have no operands; OSR/OSF are boxes (Logix form, `Storage Bit`/`Output Bit`).

## Training for production (GPU)

The CPU pilot is a smoke test (6 epochs of a nano model). For a production model:

* **Data**: 30-50k synthetic images (`--n-train 40000 --workers 16`), `--imgsz-hint 1024`; add 300+
  hand-labelled real screenshots (RSLogix 500/5000, TIA, CODESYS, phone photos of screens) for
  fine-tuning and, above all, as the validation set - synthetic-only validation over-estimates
  real-world accuracy.
* **Model/run**: `yolov8s.pt` (or `m`), `--imgsz 1024`, `--epochs 150 --hours 0`, `--batch 32 --nbs 64`,
  SGD lr0 0.01 (Ultralytics default) or AdamW 0.001 with `cos_lr=True`, `close_mosaic=15`, keep
  `fliplr=0 flipud=0`, `scale=0.5`, `patience=50`, AMP on, `--workers 8`. Budget roughly 5-10 hours
  on one A100-class GPU for 40k images x 150 epochs at 1024 (measure one epoch first and scale).
* **Full-screen screenshots** (1920 px wide, 17 px symbols) need imgsz >= 1280 or tiled inference.
* **Box classes** (TON vs TOF, GRT vs LES, ADD vs SUB...) differ only by the mnemonic text; the
  backend already OCRs the box interior, so letting the OCR'd mnemonic override the detector's
  class among box classes would remove most box confusions.
* **Export** with `train/export.py` (opset 12, static input, no NMS), then run `train/evaluate.py`,
  `train/predict_sample.py` and the backend's model integration test.

## Licence

Ultralytics (the training code, `yolov8n.pt`, and therefore the trained weights and the exported
ONNX) is **AGPL-3.0** unless you hold an Ultralytics Enterprise Licence. Running it inside a
closed-source SaaS requires that licence - or a detector with a permissive licence (e.g. YOLOX or
RT-DETR via PaddleDetection, Apache-2.0); the generator and the dataset in this folder do not
depend on Ultralytics and can train any detector. See `models/model_card.md`.
