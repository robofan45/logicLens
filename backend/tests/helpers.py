"""Shared test helpers (plain functions; fixtures live in conftest.py)."""
import io
from pathlib import Path

_HERE = Path(__file__).resolve().parent
BACKEND = _HERE.parent
REPO = BACKEND.parent
SAMPLE_IMAGE = REPO / "samples" / "ladder_logic_program_PLC1.webp"

# Ground truth for samples/ladder_logic_program_PLC1.webp (RSLogix 500, 3 rungs).
SAMPLE_TRUTH = [
    "XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);",
    "[XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);",
    "XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);",
]


def png_bytes(width=64, height=48, color=(255, 255, 255), mode="RGB", draw_lines=True) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new(mode, (width, height), color if mode != "RGBA" else color + (255,))
    if draw_lines and width > 8 and height > 8:
        d = ImageDraw.Draw(img)
        fill = (0, 0, 0) if mode == "RGB" else (0, 0, 0, 255)
        d.line([(2, height // 2), (width - 3, height // 2)], fill=fill, width=2)
        d.line([(4, 2), (4, height - 3)], fill=fill, width=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def encode(img, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()
