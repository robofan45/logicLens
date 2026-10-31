"""Contact sheets for visual QA: whole images with their labels, and zoomed symbol crops."""
from __future__ import annotations

import random
from typing import List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

from .contract import BRANCH_END, BRANCH_START, NAMES, RAIL_LEFT, RAIL_RIGHT

_SHORT = {
    "NO_Contact": "XIC", "NC_Contact": "XIO", "Positive_Transition": "P", "Negative_Transition": "N",
    "Output_Coil": "OTE", "Negated_Coil": "NCOIL", "Set_Coil": "OTL", "Reset_Coil": "OTU",
    "Branch_Start": "BS", "Branch_End": "BE", "Power_Rail_Left": "RL", "Power_Rail_Right": "RR",
}


def short_name(cid: int) -> str:
    n = NAMES[cid]
    return _SHORT.get(n, n.split("_")[0])


def color_for(cid: int) -> Tuple[int, int, int]:
    if cid in (BRANCH_START, BRANCH_END):
        return (220, 0, 220)
    if cid in (RAIL_LEFT, RAIL_RIGHT):
        return (0, 170, 220)
    if cid <= 3:
        return (0, 170, 0)
    if cid <= 7:
        return (240, 120, 0)
    return (0, 60, 255)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - old Pillow
        return ImageFont.load_default()


def draw_labels(img: Image.Image, labels: Sequence[Tuple[int, float, float, float, float]], names: bool = True,
                width: int = 1) -> Image.Image:
    out = img.convert("RGB").copy()
    d = ImageDraw.Draw(out)
    f = _font(10)
    for cid, x0, y0, x1, y1 in labels:
        c = color_for(cid)
        d.rectangle([x0, y0, x1 - 1, y1 - 1], outline=c, width=width)
        if names and cid not in (RAIL_LEFT, RAIL_RIGHT):
            d.text((x0, max(0, y0 - 11)), short_name(cid), fill=c, font=f)
    return out


def contact_sheet(items: List[Tuple[Image.Image, list, str]], cols: int = 3, cell_w: int = 640) -> Image.Image:
    thumbs = []
    for img, labels, caption in items:
        boxed = draw_labels(img, labels)
        scale = cell_w / boxed.width
        th = max(1, int(round(boxed.height * scale)))
        t = boxed.resize((cell_w, th), Image.LANCZOS)
        canvas = Image.new("RGB", (cell_w, th + 16), (255, 255, 255))
        canvas.paste(t, (0, 16))
        ImageDraw.Draw(canvas).text((4, 2), caption, fill=(0, 0, 0), font=_font(12))
        thumbs.append(canvas)
    rows = [thumbs[i:i + cols] for i in range(0, len(thumbs), cols)]
    height = sum(max(t.height for t in r) + 8 for r in rows)
    sheet = Image.new("RGB", (cols * (cell_w + 8), max(1, height)), (200, 200, 200))
    y = 0
    for r in rows:
        x = 0
        for t in r:
            sheet.paste(t, (x, y))
            x += cell_w + 8
        y += max(t.height for t in r) + 8
    return sheet


def crop_sheet(items: List[Tuple[Image.Image, list]], n: int = 60, cell: int = 168, seed: int = 0,
               cols: int = 10, small_only: bool = True) -> Image.Image:
    """Zoomed crops around random contact/coil labels with the label box drawn just outside it
    (red), so a reviewer can see whether every stroke is inside and nothing else is."""
    rng = random.Random(seed)  # nosec B311 - picks preview crops, not security
    pool = [(img, lab) for img, labels in items for lab in labels
            if lab[0] < 38 and (not small_only or lab[0] <= 7 or lab[0] in (15, 33, 34, 36, 37))]
    rng.shuffle(pool)
    sheet_rows = (min(n, len(pool)) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (cell + 4), max(1, sheet_rows) * (cell + 4)), (128, 128, 128))
    for i, (img, (cid, x0, y0, x1, y1)) in enumerate(pool[:n]):
        w, h = x1 - x0, y1 - y0
        m = max(4, int(0.3 * max(w, h)))
        box = (int(max(0, x0 - m)), int(max(0, y0 - m)), int(min(img.width, x1 + m + 1)), int(min(img.height, y1 + m + 1)))
        zoom = max(1, min(8, cell // max(box[2] - box[0], box[3] - box[1])))
        c = img.crop(box).convert("RGB").resize(((box[2] - box[0]) * zoom, (box[3] - box[1]) * zoom), Image.NEAREST)
        d = ImageDraw.Draw(c)
        d.rectangle([(x0 - box[0]) * zoom - 1, (y0 - box[1]) * zoom - 1, (x1 - box[0]) * zoom, (y1 - box[1]) * zoom],
                    outline=(255, 0, 0), width=1)
        d.text((2, 2), short_name(cid), fill=(255, 0, 0), font=_font(11))
        sheet.paste(c, ((i % cols) * (cell + 4), (i // cols) * (cell + 4)))
    return sheet
