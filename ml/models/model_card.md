# Model card: `logiclens-yolov8n.onnx` (CPU pilot)

| | |
|---|---|
| Task | Detect ladder-logic symbols in diagram images for the LogicLens backend assembler (`backend/app/engines/yolo_onnx.py` + `assembler.py`) |
| Architecture | Ultralytics YOLOv8n, 3.0 M parameters, 8.2 GFLOPs at 640 (~10.8 at 736) |
| File | `ml/models/logiclens-yolov8n.onnx`, 12.8 MB, SHA-256 `437cbe561608e0bdb3a4c8639415b07c8670f9e76c61aa70c3b3e2a41a8c8241` |
| I/O | input `images` float32 [1, 3, 736, 736] (RGB / 255, letterboxed, pad 114); output `output0` [1, 48, 11109] = cx, cy, w, h in letterboxed px + 44 sigmoid class scores. Opset 12, static shapes, **no NMS in the graph**. |
| Classes | 44, in `contract/classes.json` order (names embedded in the ONNX metadata). 38/39 (wires) never trained: ignore them. |
| Status | **Pilot.** Trained 1.6 h on 2 shared CPU cores from synthetic data only. Good enough to exercise the pipeline end to end; not a production model. |
| Licence | **AGPL-3.0** (see below) |

## Data (synthetic only)

`ml/generator` dataset v2, seed 1 (`reports/dataset_report.md`): 2000 train / 300 val / 300 test images,
34,682 / 5,167 / 5,327 labels. Six visual styles (RSLogix 500-like 29 %, Studio 5000-like 19 %,
TIA-like 15 %, IEC/CODESYS-like 13 %, printed 12 %, dark IDE 12 %), four operand styles (SLC
addresses, Logix tags, TIA %-addresses and quoted symbols, IEC identifiers), 34 % clean / 41 %
lightly / 25 % heavily augmented (perspective, rotation <= 2 deg, scale, lighting, moire, blur,
noise, JPEG). Programs are sampled from realistic templates, parsed by the contract parser, and
split by a hash of the program text (no program in two splits). Every symbol class has >= 194
training instances. Long image side 247-1902 px; the smallest contact is >= ~14 px after
letterboxing to 736 (p05 14.7 px, median 17 px). **No real screenshot was used for training or
for the metrics below**; the only real image is the qualitative check further down.

## Training

`python train/train.py --data data/v2/dataset.yaml --hours 1.6 --imgsz 736 --batch 8 --nbs 16 --threads 2`

* Initialised from COCO `yolov8n.pt` (Ultralytics assets v8.3.0, SHA-256 pinned in train.py); 349/355
  tensors transferred (the class head is new).
* AdamW lr0 0.002 -> lrf 0.05 (linear), momentum 0.9, weight decay 5e-4, warm-up 0.5 epoch (bias LR
  0.01), batch 8 with gradient accumulation to 16, mosaic 1.0 closed for the last epoch, scale 0.3,
  translate 0.1, HSV (0.015, 0.4, 0.3), **no flips** (rails/connectors/NC slash are handed), no
  rotation/shear/perspective in Ultralytics (the generator does that with exact boxes), seed 0,
  deterministic.
* Hardware: 2 shared vCPU (Xeon 2.8 GHz), torch 2.15.0+cpu with 2 threads, `nice -n 15`, workers 0,
  no GPU. Ultralytics 8.4.194.
* Wall-clock budget `time=1.6` h: Ultralytics planned 7 epochs; 6 full epochs + 33 % of the 7th
  (the mosaic-free one) ran before the cut. Total wall time 97.3 min including final validation.

| epoch | 1 | 2 | 3 | 4 | 5 | 6 | 7 (33 %, no mosaic) |
|---|---|---|---|---|---|---|---|
| val mAP50 | 0.493 | 0.636 | 0.696 | 0.819 | 0.852 | 0.862 | **0.896** |
| val mAP50-95 | 0.398 | 0.554 | 0.615 | 0.746 | 0.779 | 0.793 | **0.825** |

Still improving when the budget ran out: the model is under-trained.

## Metrics (synthetic test split, 300 images, exported ONNX, `train/evaluate.py`)

| P | R | mAP50 | mAP50-95 |
|---|---|---|---|
| 0.844 | 0.859 | **0.891** | **0.821** |

CPU latency per image with the backend's exact pipeline (letterbox + onnxruntime + decode/NMS), this
2-vCPU shared box: **1 thread p50 135 ms / p95 151 ms; 2 threads p50 96 ms / p95 114 ms**. One
2-core worker saturates at 2 concurrent requests (~13 req/s); beyond that p95 grows linearly with
queueing (369 ms at 4, 713 ms at 8 concurrent users). No memory growth over 600 inferences.

Per class (test split; "train inst." from the dataset report):

| id | class | train inst. | test inst. | P | R | mAP50 | mAP50-95 |
|---|---|---|---|---|---|---|---|
| 0 | NO_Contact | 8828 | 1376 | 0.998 | 1.000 | 0.995 | 0.909 |
| 1 | NC_Contact | 3686 | 571 | 0.999 | 1.000 | 0.995 | 0.902 |
| 2 | Positive_Transition | 329 | 52 | 0.988 | 1.000 | 0.995 | 0.915 |
| 3 | Negative_Transition | 255 | 45 | 0.988 | 1.000 | 0.995 | 0.924 |
| 4 | Output_Coil | 2720 | 422 | 0.998 | 1.000 | 0.995 | 0.905 |
| 5 | Negated_Coil | 338 | 52 | 0.989 | 1.000 | 0.995 | 0.917 |
| 6 | Set_Coil | 702 | 99 | 0.921 | 1.000 | 0.986 | 0.905 |
| 7 | Reset_Coil | 655 | 81 | 0.987 | 0.949 | 0.985 | 0.907 |
| 8 | TON_Timer | 253 | 33 | 0.589 | 0.909 | 0.903 | 0.897 |
| 9 | TOF_Timer | 246 | 36 | 0.838 | 0.972 | 0.977 | 0.967 |
| 10 | RTO_Timer | 247 | 39 | 0.817 | 0.949 | 0.951 | 0.947 |
| 11 | TP_Timer | 216 | 26 | 0.883 | 0.871 | 0.940 | 0.938 |
| 12 | CTU_Counter | 248 | 45 | 0.978 | 0.978 | 0.990 | 0.982 |
| 13 | CTD_Counter | 248 | 40 | 0.784 | 0.950 | 0.966 | 0.961 |
| 14 | CTUD_Counter | 217 | 25 | 0.638 | 1.000 | 0.853 | 0.842 |
| 15 | RES_Reset | 255 | 46 | 1.000 | 0.987 | 0.995 | 0.913 |
| 16 | EQU_Equal | 254 | 37 | 0.893 | 0.946 | 0.978 | 0.959 |
| 17 | NEQ_NotEqual | 242 | 42 | 0.905 | 0.691 | 0.853 | 0.838 |
| 18 | GRT_GreaterThan | 216 | 31 | 0.703 | 0.871 | 0.883 | 0.876 |
| 19 | LES_LessThan | 260 | 42 | 0.614 | 0.682 | 0.792 | 0.777 |
| 20 | GEQ_GreaterEqual | 212 | 35 | 0.356 | 0.457 | 0.488 | 0.472 |
| 21 | LEQ_LessEqual | 207 | 37 | 0.382 | 0.786 | 0.508 | 0.501 |
| 22 | ADD_Addition | 204 | 33 | 0.707 | 0.697 | 0.809 | 0.778 |
| 23 | SUB_Subtraction | 194 | 38 | 0.829 | 0.500 | 0.731 | 0.717 |
| 24 | MUL_Multiplication | 195 | 20 | 1.000 | 0.529 | 0.744 | 0.743 |
| 25 | DIV_Division | 240 | 27 | 0.998 | 1.000 | 0.995 | 0.975 |
| 26 | MOV_Move | 589 | 86 | 0.868 | 0.965 | 0.985 | 0.975 |
| 27 | OSR_OneShotRising | 238 | 44 | 0.972 | 0.977 | 0.994 | 0.980 |
| 28 | OSF_OneShotFalling | 219 | 34 | 0.949 | 1.000 | 0.994 | 0.994 |
| 29 | AND_Bitwise | 232 | 26 | 0.483 | 0.423 | 0.636 | 0.631 |
| 30 | OR_Bitwise | 229 | 37 | 0.599 | 0.946 | 0.812 | 0.797 |
| 31 | XOR_Bitwise | 229 | 34 | 0.437 | 0.412 | 0.458 | 0.451 |
| 32 | NOT_Bitwise | 300 | 51 | 0.888 | 0.932 | 0.957 | 0.954 |
| 33 | JMP_Jump | 271 | 45 | 0.837 | 1.000 | 0.995 | 0.923 |
| 34 | LBL_Label | 252 | 39 | 0.984 | 1.000 | 0.995 | 0.911 |
| 35 | JSR_Subroutine | 329 | 40 | 0.983 | 1.000 | 0.995 | 0.962 |
| 36 | MCR_MasterControl | 246 | 39 | 0.986 | 1.000 | 0.995 | 0.913 |
| 37 | END_End | 431 | 68 | 0.991 | 1.000 | 0.995 | 0.917 |
| 40 | Branch_Start | 2725 | 427 | 0.962 | 0.994 | 0.988 | 0.621 |
| 41 | Branch_End | 2725 | 427 | 0.970 | 0.991 | 0.993 | 0.604 |
| 42 | Power_Rail_Left | 2000 | 300 | 0.919 | 0.341 | 0.684 | 0.232 |
| 43 | Power_Rail_Right | 2000 | 300 | 0.819 | 0.357 | 0.657 | 0.228 |

## The real screenshot (`samples/ladder_logic_program_PLC1.webp`, RSLogix 500, 892 x 508)

`train/predict_sample.py` -> `ml/reports/sample_prediction.png` / `.json`, conf 0.25:

* All 14 hand-labelled objects detected with the right class, **no false positives**. 13/14 at IoU
  >= 0.5 (contacts/coils 0.80-0.92, connectors 0.93-0.95, left rail 0.92); the right rail was found
  (conf 0.52) with a box 14 px wide instead of 7, IoU 0.49. Symbol confidences 0.85-0.90.
* Detections + backend assembler + real Tesseract OCR give exactly the ground truth for all three
  rungs: `XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);` `[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);`
  `XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);` - and the backend's own
  `tests/integration/test_redis_and_model.py::test_real_sample_through_the_trained_yolo_model` passes.
* Caveat: this is one clean screenshot of the style the generator imitates most closely. It is a
  smoke test, not evidence of real-world accuracy.

## Known weaknesses

1. **Synthetic-only.** Real screenshots from other software versions, colour schemes, DPI scaling,
   fonts (MS Sans Serif, Tahoma, Segoe) and especially phone photos of screens will be worse than the
   synthetic test numbers. A few hundred labelled real images are needed to measure and fix this.
2. **Box instructions are told apart only by their mnemonic text.** Confusions inside families:
   GEQ/LEQ (mAP50 0.49/0.51), XOR/AND/OR (0.46/0.64/0.81), ADD/SUB/MUL (0.81/0.73/0.74), LES/NEQ, CTUD,
   TON. The box itself is found reliably; the class is the weak part. Recommended backend fix: the
   assembler already OCRs the box interior - let the OCR'd mnemonic override the detected class
   within the box classes.
3. **Power rails**: recall 0.34-0.36 at IoU 0.5 and loose boxes. A 5-7 px wide, full-height box rarely
   contains a stride-32 anchor centre, and only the P5 head can regress that height. The assembler
   uses rails only to bound OCR crops, so the impact is small; a production run at higher
   resolution, or wider rail labels, should fix it.
4. **Branch connectors** are found (mAP50 0.99) but their vertical extent is loose (mAP50-95 0.61);
   the assembler pairs connectors by vertical overlap (>= 0.6) and assigns rows within their span,
   so very tall/nested branches are where to look first if rungs mis-assemble.
5. **Scale**: trained with contacts >= ~14 px after letterboxing to 736. A full-screen 1920 px
   screenshot at 100 % zoom shrinks 17 px contacts to ~6.5 px: crop to the ladder area first, tile,
   or retrain at 1024-1280.
6. **Under-trained**: 6.3 epochs on CPU; still improving at the cut.
7. **Conventions are contract section 6**, not every vendor's: TIA's real compare boxes (operands
   above/below), pin-style operands outside boxes, rung-continuation markers, multi-column or
   page-broken ladders, FBD/ST are not in the training data. LIM, ONS, AFI, NOP have no class.
8. Synthetic text uses Liberation/DejaVu/FreeFont families (system fonts, rendered into images).

## Reproduce

```
python -m generator.generate --out data/v2 --n-train 2000 --n-val 300 --n-test 300 --seed 1 --imgsz-hint 736
nice -n 15 python train/train.py --data data/v2/dataset.yaml --hours 1.6 --imgsz 736 --batch 8 --nbs 16 --threads 2 --name pilot
python train/export.py --weights runs/pilot/weights/best.pt --imgsz 736 --opset 12 --out models/logiclens-yolov8n.onnx
python train/evaluate.py --model models/logiclens-yolov8n.onnx --data data/v2/dataset.yaml
python train/predict_sample.py --model models/logiclens-yolov8n.onnx
```

The dataset is byte-reproducible for a seed. Training on CPU is deterministic in Ultralytics'
sense (`deterministic=True`, seed 0) but the time budget makes the number of completed iterations
depend on machine load, so a re-run gives a similar, not identical, model.

## Licence

Ultralytics' training code and the `yolov8n.pt` it starts from are **AGPL-3.0**; Ultralytics treats
models trained with it (and their exports - the ONNX metadata says `AGPL-3.0 License`) as covered
too. Serving this model inside a closed-source SaaS therefore needs an **Ultralytics Enterprise
Licence**, or replacing it with a permissively licensed detector (for example YOLOX or RT-DETR from
PaddleDetection, both Apache-2.0) trained on the same data - the generator and dataset in ml/ have
no Ultralytics dependency. Note that the backend decoder expects the YOLOv8 output layout
[1, 4 + nc, N]; another detector needs an export with that layout or a decoder change.
