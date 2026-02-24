"""
generate_plc_dataset.py

Generates a synthetic PLC ladder logic image dataset for YOLO training.

Usage:
    python generate_plc_dataset.py [--output plc_dataset] [--count 500] [--seed 42]

Each generated image contains a randomly assembled ladder rung drawn on a white canvas.
Corresponding YOLO-format label files (.txt) are written alongside the images.
A dataset.yaml is produced at the root of the output directory.
"""

import argparse
import logging
import math
import os
import random
import textwrap
from typing import Dict, List, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Class registry (must match services/yolo_service.py PLC_CLASSES)
# ---------------------------------------------------------------------------
CLASS_NAMES: List[str] = [
    "NO_Contact",       # 0
    "NC_Contact",       # 1
    "Positive_Transition",  # 2
    "Negative_Transition",  # 3
    "Output_Coil",      # 4
    "Negated_Coil",     # 5
    "Set_Coil",         # 6
    "Reset_Coil",       # 7
    "TON_Timer",        # 8
    "TOF_Timer",        # 9
    "RTO_Timer",        # 10
    "TP_Timer",         # 11
    "CTU_Counter",      # 12
    "CTD_Counter",      # 13
    "CTUD_Counter",     # 14
    "RES_Reset",        # 15
    "EQU_Equal",        # 16
    "NEQ_NotEqual",     # 17
    "GRT_GreaterThan",  # 18
    "LES_LessThan",     # 19
    "GEQ_GreaterEqual", # 20
    "LEQ_LessEqual",    # 21
    "ADD_Addition",     # 22
    "SUB_Subtraction",  # 23
    "MUL_Multiplication",  # 24
    "DIV_Division",     # 25
    "MOV_Move",         # 26
    "OSR_OneShotRising",    # 27
    "OSF_OneShotFalling",   # 28
    "Wire_Horizontal",  # 29
    "Wire_Vertical",    # 30
    "Branch_Start",     # 31
    "Branch_End",       # 32
    "Power_Rail_Left",  # 33
    "Power_Rail_Right", # 34
    # aliases / additional styles
    "TON_Timer",        # 35
    "CTU_Counter",      # 36
    "NO_Contact",       # 37
    "NC_Contact",       # 38
    "Output_Coil",      # 39
    "Set_Coil",         # 40
    "Reset_Coil",       # 41
    "Wire_Horizontal",  # 42
    "Unknown",          # 43
]
CLASS_INDEX: Dict[str, int] = {name: idx for idx, name in enumerate(CLASS_NAMES)}

# Canvas and element dimensions
CANVAS_W = 640
CANVAS_H = 480
ELEM_W = 50
ELEM_H = 40
RAIL_W = 8
WIRE_THICKNESS = 2
FONT = cv2.FONT_HERSHEY_SIMPLEX
FONT_SCALE = 0.35
FONT_COLOR = (0, 0, 0)

CONTACT_CLASSES = [0, 1, 27, 28]     # NO, NC, OSR, OSF
OUTPUT_CLASSES = [4, 5, 6, 7]        # coils
TIMER_CLASSES = [8, 9, 10, 11]
COUNTER_CLASSES = [12, 13, 14]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_no_contact(img: np.ndarray, cx: int, cy: int) -> Tuple[int, int, int, int]:
    """Draw a Normally-Open contact symbol [  | |  ] and return bbox."""
    x1, y1 = cx - ELEM_W // 2, cy - ELEM_H // 2
    x2, y2 = cx + ELEM_W // 2, cy + ELEM_H // 2
    # Horizontal wires
    cv2.line(img, (x1, cy), (cx - 8, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx + 8, cy), (x2, cy), FONT_COLOR, WIRE_THICKNESS)
    # Vertical bars
    cv2.line(img, (cx - 8, cy - 12), (cx - 8, cy + 12), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx + 8, cy - 12), (cx + 8, cy + 12), FONT_COLOR, WIRE_THICKNESS)
    cv2.putText(img, "NO", (x1, y1 - 2), FONT, FONT_SCALE, FONT_COLOR, 1)
    return x1, y1, x2, y2


def _draw_nc_contact(img: np.ndarray, cx: int, cy: int) -> Tuple[int, int, int, int]:
    """Draw a Normally-Closed contact symbol [  |/|  ]."""
    x1, y1 = cx - ELEM_W // 2, cy - ELEM_H // 2
    x2, y2 = cx + ELEM_W // 2, cy + ELEM_H // 2
    cv2.line(img, (x1, cy), (cx - 8, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx + 8, cy), (x2, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx - 8, cy - 12), (cx - 8, cy + 12), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx + 8, cy - 12), (cx + 8, cy + 12), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx - 6, cy + 10), (cx + 6, cy - 10), FONT_COLOR, WIRE_THICKNESS)
    cv2.putText(img, "NC", (x1, y1 - 2), FONT, FONT_SCALE, FONT_COLOR, 1)
    return x1, y1, x2, y2


def _draw_output_coil(img: np.ndarray, cx: int, cy: int) -> Tuple[int, int, int, int]:
    """Draw an output coil symbol  ---( )---."""
    x1, y1 = cx - ELEM_W // 2, cy - ELEM_H // 2
    x2, y2 = cx + ELEM_W // 2, cy + ELEM_H // 2
    cv2.line(img, (x1, cy), (cx - 14, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (cx + 14, cy), (x2, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.circle(img, (cx, cy), 14, FONT_COLOR, WIRE_THICKNESS)
    cv2.putText(img, "OUT", (x1, y1 - 2), FONT, FONT_SCALE, FONT_COLOR, 1)
    return x1, y1, x2, y2


def _draw_timer(img: np.ndarray, cx: int, cy: int, label: str = "TON") -> Tuple[int, int, int, int]:
    """Draw a timer function block."""
    x1, y1 = cx - ELEM_W // 2, cy - ELEM_H // 2
    x2, y2 = cx + ELEM_W // 2, cy + ELEM_H // 2
    cv2.rectangle(img, (x1, y1), (x2, y2), FONT_COLOR, WIRE_THICKNESS)
    cv2.putText(img, label, (x1 + 4, cy + 4), FONT, FONT_SCALE, FONT_COLOR, 1)
    cv2.line(img, (x1 - 20, cy), (x1, cy), FONT_COLOR, WIRE_THICKNESS)
    cv2.line(img, (x2, cy), (x2 + 20, cy), FONT_COLOR, WIRE_THICKNESS)
    return x1 - 20, y1, x2 + 20, y2


def _draw_power_rail(img: np.ndarray, x: int, h: int) -> Tuple[int, int, int, int]:
    """Draw a vertical power rail."""
    cv2.line(img, (x, 0), (x, h), FONT_COLOR, RAIL_W)
    return x - RAIL_W // 2, 0, x + RAIL_W // 2, h


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

ELEM_DRAW_FUNCS = {
    0: _draw_no_contact,
    1: _draw_nc_contact,
    4: _draw_output_coil,
    8: lambda img, cx, cy: _draw_timer(img, cx, cy, "TON"),
    9: lambda img, cx, cy: _draw_timer(img, cx, cy, "TOF"),
    12: lambda img, cx, cy: _draw_timer(img, cx, cy, "CTU"),
}


def _generate_image(rng: random.Random) -> Tuple[np.ndarray, List[Tuple[int, int, int, int, int]]]:
    """
    Generate one synthetic ladder diagram image.
    Returns (image_bgr, [(class_id, cx, cy, w, h), ...]) in absolute pixel coords.
    """
    img = np.full((CANVAS_H, CANVAS_W, 3), 255, dtype=np.uint8)

    annotations: List[Tuple[int, int, int, int, int]] = []

    # Power rails
    left_x = 30
    right_x = CANVAS_W - 30
    _draw_power_rail(img, left_x, CANVAS_H)
    _draw_power_rail(img, right_x, CANVAS_H)
    annotations.append((CLASS_INDEX["Power_Rail_Left"], left_x, CANVAS_H // 2, RAIL_W, CANVAS_H))
    annotations.append((CLASS_INDEX["Power_Rail_Right"], right_x, CANVAS_H // 2, RAIL_W, CANVAS_H))

    num_rungs = rng.randint(1, 4)
    row_height = (CANVAS_H - 20) // num_rungs

    for rung_idx in range(num_rungs):
        cy = 20 + rung_idx * row_height + row_height // 2
        num_contacts = rng.randint(1, 3)
        contact_classes = rng.choices(CONTACT_CLASSES, k=num_contacts)

        x_cursor = left_x + 30
        step = (right_x - x_cursor - 60) // (num_contacts + 1)

        for cls_id in contact_classes:
            cx = x_cursor + ELEM_W // 2
            draw_fn = ELEM_DRAW_FUNCS.get(cls_id, ELEM_DRAW_FUNCS[0])
            bx1, by1, bx2, by2 = draw_fn(img, cx, cy)
            bw = bx2 - bx1
            bh = by2 - by1
            annotations.append((cls_id, cx, cy, bw, bh))
            x_cursor += step

        # Output element
        out_cls = rng.choice(OUTPUT_CLASSES)
        out_cx = right_x - 40
        draw_fn = ELEM_DRAW_FUNCS.get(out_cls, ELEM_DRAW_FUNCS[4])
        bx1, by1, bx2, by2 = draw_fn(img, out_cx, cy)
        annotations.append((out_cls, out_cx, cy, bx2 - bx1, by2 - by1))

        # Connecting horizontal wire
        cv2.line(img, (left_x + RAIL_W, cy), (right_x - RAIL_W, cy), FONT_COLOR, WIRE_THICKNESS)

    # Add slight noise
    noise = np.random.randint(0, 15, img.shape, dtype=np.uint8)
    img = cv2.add(img, noise)

    return img, annotations


def _yolo_label(annotations: List[Tuple[int, int, int, int, int]], img_w: int, img_h: int) -> str:
    lines = []
    for cls_id, cx, cy, w, h in annotations:
        xc = cx / img_w
        yc = cy / img_h
        wn = w / img_w
        hn = h / img_h
        xc = max(0.0, min(1.0, xc))
        yc = max(0.0, min(1.0, yc))
        wn = max(0.001, min(1.0, wn))
        hn = max(0.001, min(1.0, hn))
        lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {wn:.6f} {hn:.6f}")
    return "\n".join(lines)


def _write_dataset_yaml(output_dir: str, train_path: str, val_path: str) -> None:
    nc = len(CLASS_NAMES)
    names_str = "\n".join(f"  {i}: {name}" for i, name in enumerate(CLASS_NAMES))
    yaml_content = textwrap.dedent(
        f"""\
        path: {os.path.abspath(output_dir)}
        train: {train_path}
        val: {val_path}
        nc: {nc}
        names:
        {names_str}
        """
    )
    yaml_path = os.path.join(output_dir, "dataset.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    logger.info("Dataset YAML written to %s", yaml_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def generate(output_dir: str = "plc_dataset", count: int = 500, seed: int = 42) -> None:
    rng = random.Random(seed)
    np.random.seed(seed)

    train_img_dir = os.path.join(output_dir, "images", "train")
    train_lbl_dir = os.path.join(output_dir, "labels", "train")
    val_img_dir = os.path.join(output_dir, "images", "val")
    val_lbl_dir = os.path.join(output_dir, "labels", "val")

    for d in (train_img_dir, train_lbl_dir, val_img_dir, val_lbl_dir):
        os.makedirs(d, exist_ok=True)

    val_count = max(1, count // 10)
    train_count = count - val_count

    for i in range(train_count):
        img, annots = _generate_image(rng)
        img_path = os.path.join(train_img_dir, f"img_{i:05d}.jpg")
        lbl_path = os.path.join(train_lbl_dir, f"img_{i:05d}.txt")
        cv2.imwrite(img_path, img)
        with open(lbl_path, "w", encoding="utf-8") as f:
            f.write(_yolo_label(annots, CANVAS_W, CANVAS_H))

    for i in range(val_count):
        img, annots = _generate_image(rng)
        img_path = os.path.join(val_img_dir, f"val_{i:05d}.jpg")
        lbl_path = os.path.join(val_lbl_dir, f"val_{i:05d}.txt")
        cv2.imwrite(img_path, img)
        with open(lbl_path, "w", encoding="utf-8") as f:
            f.write(_yolo_label(annots, CANVAS_W, CANVAS_H))

    _write_dataset_yaml(output_dir, "images/train", "images/val")
    logger.info("Generated %d train + %d val images in '%s'.", train_count, val_count, output_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic PLC ladder logic dataset.")
    parser.add_argument("--output", type=str, default="plc_dataset")
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(output_dir=args.output, count=args.count, seed=args.seed)
