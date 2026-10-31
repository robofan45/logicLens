"""Operand OCR for the YOLO assembler.

Tesseract is called as a subprocess over stdin/stdout with PNG bytes, never through temporary
files (pytesseract writes every crop to /tmp, which would break the zero-retention rule). All crops
of one kind are pasted into a single tall "sheet" and read in one call with TSV output; each word
is mapped back to its crop by its y position. Small RSLogix text (~10 px) is read with a short
ensemble of preprocessing variants and a vote over normalised candidates.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import re
import shutil
import subprocess  # nosec B404  # tesseract runs with a fixed argv, no shell, input over stdin
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Iterable, List, Optional, Protocol, Sequence, Tuple

import numpy as np
from PIL import Image

from ..vendor.logiclens_ladder import classify_operand

log = logging.getLogger("logiclens.ocr")

Region = Tuple[int, int, int, int]


@dataclass
class OcrRequest:
    key: Hashable
    region: Region          # x1, y1, x2, y2 in source-image pixels
    kind: str               # "operand" (one line), "digits" (bit number), "block" (box interior)
    symbol_edge: Optional[str] = None  # "bottom"/"top": the symbol touches that edge of the region;
                                       # keep the text band closest to it, drop strokes touching it


class Ocr(Protocol):
    def read(self, image: Optional[Image.Image], requests: Sequence[OcrRequest]) -> Dict[Hashable, str]: ...


# ============================================================================ text normalisation
_DIGITLIKE = {"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "i": "1", "|": "1", "]": "1", "[": "1",
              "!": "1", "L": "1", "Z": "2", "z": "2", "S": "5", "s": "5", "B": "8", "g": "9"}
_FILE_LETTER = {"1": "I", "l": "I", "|": "I", "[": "I", "]": "I", "!": "I", "i": "I", "0": "O", "o": "O",
                "Q": "O", "q": "O"}
_SLC_HEAD = re.compile(r"^(?:[A-Z]|ST|MG|PD|BT)\d{0,3}$")
_SLC_FULL = re.compile(r"^(?:[A-Z]|ST|MG|PD|BT)\d{0,3}:\d+(?:/\d+)?(?:\.[A-Z]+|\.\d+)?$")
_SPLIT_FILE_PART = re.compile(r"^(?:[A-Z]|ST|MG|PD|BT)\d{0,3}:\d+$")
_KEEP = re.compile(r"[^A-Za-z0-9_:./\[\]%#\-+\"]")


def _digits(text: str) -> str:
    return "".join(_DIGITLIKE.get(c, c) for c in text)


def _normalize_slc(s: str) -> Optional[str]:
    head, tail = s.split(":", 1)
    if not head or len(head) > 4 or not tail:
        return None
    if re.fullmatch(r"[Qq][Oo0]", head):
        head = "O"
    c0, rest = head[0], head[1:]
    if len(head) == 1 or not c0.isalpha() or c0 in "lio":
        # 'Q:2' is not an SLC address (the label file is Q2:), so a lone Q is a misread O
        first = _FILE_LETTER.get(c0, c0).upper()
    else:
        first = c0.upper()
    if len(rest) and rest[0].isalpha() and (first + rest[0].upper()) in ("ST", "MG", "PD", "BT"):
        first, rest = first + rest[0].upper(), rest[1:]
    head = first + _digits(rest)
    if not _SLC_HEAD.match(head):
        return None
    m = re.match(r"^([^/.]*)(?:/([^.]*))?(?:\.(.*))?$", tail)
    if not m:  # pragma: no cover - the pattern matches any string
        return None
    element, bit, sub = m.group(1), m.group(2), m.group(3)
    out = f"{head}:{_digits(element)}"
    if bit is not None:
        out += f"/{_digits(bit)}"
    if sub is not None:
        out += "." + (sub.upper() if sub.isalpha() else _digits(sub))
    return out if _SLC_FULL.match(out) else None


_SIEMENS = re.compile(r"^%([IQM])([BWDX]?)(\d+)(?:\.(\d))?$")
_AREA = {"1": "I", "l": "I", "|": "I", "i": "I", "I": "I", "0": "Q", "O": "Q", "o": "Q", "Q": "Q", "M": "M", "m": "M"}
_LOGIX_MODULE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(\w+):([1lI|iO0oQCS])\.(.+)$")
_MODULE_TYPE = {"1": "I", "l": "I", "I": "I", "|": "I", "i": "I", "0": "O", "O": "O", "o": "O", "Q": "O", "C": "C", "S": "S"}


def _normalize_siemens(s: str) -> Optional[str]:
    """%10.1 -> %I0.1, %OO.3 -> %Q0.3, %MW1O -> %MW10: the area letter after % is never a digit."""
    if len(s) < 3 or s[0] != "%":
        return None
    area = _AREA.get(s[1])
    if area is None:
        return None
    rest = s[2:]
    size = ""
    if rest[:1].upper() in ("B", "W", "D", "X") and len(rest) > 1 and not rest[1:2].isalpha():
        size, rest = rest[0].upper(), rest[1:]
    out = f"%{area}{size}{_digits(rest)}"
    return out if _SIEMENS.match(out) else None


def _normalize_logix_module(s: str) -> Optional[str]:
    """Local:3:1.Data.2 -> Local:3:I.Data.2 (module type is I, O, C or S)."""
    m = _LOGIX_MODULE.match(s)
    if not m:
        return None
    kind = _MODULE_TYPE.get(m.group(3))
    return f"{m.group(1)}:{_digits(m.group(2))}:{kind}.{m.group(4)}" if kind else None


def normalize_operand(raw: str) -> str:
    """Clean one OCR'd operand: drop whitespace and RSLogix live-value markers, fix the usual
    letter/digit confusions inside SLC addresses (I:]->I:1, 0:2->O:2, B3:O/l->B3:0/1)."""
    s = "".join((raw or "").split())
    s = s.rstrip("<>?").strip("~`'\",;")
    if not s:
        return ""
    op = classify_operand(s)
    if op is not None and op.type == "number":
        return s
    if s.startswith("%"):
        siemens = _normalize_siemens(_KEEP.sub("", s))
        if siemens:
            return siemens
    if s.count(":") >= 2:
        module = _normalize_logix_module(_KEEP.sub("", s))
        if module:
            return module
    if ":" in s and not s.lower().startswith("local"):
        slc = _normalize_slc(s)
        if slc:
            return slc
    return _KEEP.sub("", s)


def join_split_address(above: str, below: str) -> str:
    """RSLogix 500 prints 'I:1' above a contact and the bit '1' below: join them as 'I:1/1'."""
    below = (below or "").strip()
    if above and _SPLIT_FILE_PART.match(above) and re.fullmatch(r"\d{1,2}", below):
        return f"{above}/{below}"
    return above


def _is_address(s: str) -> bool:
    return bool(_SLC_FULL.match(s))


def vote(candidates: Iterable[str]) -> str:
    """Pick the reading most variants agree on; ties prefer SLC-looking addresses, then the
    earliest (preferred) variant."""
    normed = [normalize_operand(c) for c in candidates]
    valid = [(i, c) for i, c in enumerate(normed) if c and classify_operand(c) is not None]
    if not valid:
        return ""
    counts = Counter(c for _, c in valid)
    first_seen: Dict[str, int] = {}
    for i, c in valid:
        first_seen.setdefault(c, i)
    return max(counts, key=lambda c: (counts[c], _is_address(c), -first_seen[c]))


# ============================================================================ box instructions
_BOX_LABELS = [
    ("time base", "base"), ("timebase", "base"), ("base", "base"), ("timer", "timer"), ("counter", "counter"),
    ("preset", "preset"), ("accum", "accum"), ("source a", "a"), ("source b", "b"), ("source", "source"),
    ("destination", "dest"), ("dest", "dest"), ("routine name", "routine"), ("routine", "routine"),
    ("storage bit", "storage"), ("output bit", "output"), ("low lim", "low"), ("high lim", "high"),
    ("test", "test"),
]
_DESCRIPTIONS = (
    "timer on delay", "timer off delay", "retentive timer", "timer pulse", "count up", "count down",
    "up/down counter", "move", "greater than", "less than", "equal", "not equal", "grtr than", "add",
    "subtract", "multiply", "divide", "bitwise", "jump to subroutine", "one shot", "limit test", "masked move",
)
_SLOTS = {
    **{m: ["timer", "base", "preset", "accum"] for m in ("TON", "TOF", "RTO")},
    "TP": ["timer", "preset", "accum"],
    **{m: ["counter", "preset", "accum"] for m in ("CTU", "CTD", "CTUD")},
    **{m: ["a", "b"] for m in ("EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ")},
    "LIM": ["low", "test", "high"],
    **{m: ["a", "b", "dest"] for m in ("ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR")},
    **{m: ["source", "dest"] for m in ("MOV", "NOT")},
    **{m: ["storage", "output"] for m in ("OSR", "OSF")},
    "JSR": ["routine"],
}
_FALLBACK = {"a": "source", "source": "a"}


_BOX_MNEMONICS = {m for m in _SLOTS}
_DESCRIPTION_TO_MNEMONIC = {
    "timer on delay": "TON", "timer off delay": "TOF", "retentive timer": "RTO", "timer pulse": "TP",
    "count up": "CTU", "count down": "CTD", "up/down counter": "CTUD", "greater than or eql": "GEQ",
    "greater than or equal": "GEQ", "less than or eql": "LEQ", "less than or equal": "LEQ", "greater than": "GRT",
    "grtr than": "GRT", "less than": "LES", "not equal": "NEQ", "equal": "EQU", "add": "ADD", "subtract": "SUB",
    "multiply": "MUL", "divide": "DIV", "move": "MOV", "limit test": "LIM", "jump to subroutine": "JSR",
}


def box_mnemonic(text: str) -> Optional[str]:
    """The instruction a box says it is (its header row), when the OCR could read it."""
    for raw_line in (text or "").splitlines()[:3]:
        line = " ".join(raw_line.split())
        if not line:
            continue
        head = re.sub(r"[^A-Za-z]", "", line.split(" ")[0]).upper()
        if head in _BOX_MNEMONICS:
            return head
        low = line.lower()
        for desc in sorted(_DESCRIPTION_TO_MNEMONIC, key=len, reverse=True):
            if low.startswith(desc):
                return _DESCRIPTION_TO_MNEMONIC[desc]
    return None


def parse_box_text(mnemonic: str, text: str) -> List[str]:
    """Map the text inside a box instruction to its LLT operands in order ('?' when unreadable)."""
    slots = _SLOTS.get(mnemonic, [])
    found: Dict[str, str] = {}
    pending: Optional[str] = None
    for raw_line in (text or "").splitlines():
        line = " ".join(raw_line.split())
        low = line.lower()
        if not line or low == mnemonic.lower() or low.startswith(_DESCRIPTIONS):
            continue
        for label, slot in _BOX_LABELS:
            if low.startswith(label + " ") or low == label:
                value = line[len(label):].strip().split(" ")[0] if len(line) > len(label) else ""
                value = normalize_operand(value)
                if value and classify_operand(value) is not None:
                    found.setdefault(slot, value)
                    pending = None
                else:
                    pending = slot
                break
        else:
            if pending and pending not in found:
                value = normalize_operand(line.split(" ")[0])
                if value and classify_operand(value) is not None:
                    found[pending] = value
            pending = None
    out: List[str] = []
    for slot in slots:
        if slot == "base" and "base" not in found:
            continue  # Logix timers have no time base: TON(T, preset, accum)
        value = found.get(slot) or found.get(_FALLBACK.get(slot, ""), "")
        out.append(value or "?")
    return out


# ============================================================================ TSV
def parse_tsv(tsv: str, bands: Sequence[Tuple[int, int]], multiline: bool) -> List[str]:
    """Words from Tesseract's TSV grouped into the sheet bands they fall in."""
    words: List[List[Tuple[Tuple[int, int, int], int, int, str]]] = [[] for _ in bands]
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        text = (row.get("text") or "").strip()
        if row.get("level") != "5" or not text:
            continue
        try:
            top, height, left = int(row["top"]), int(row["height"]), int(row["left"])
            line_key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        except (KeyError, TypeError, ValueError):
            continue
        cy = top + height / 2
        for i, (y0, y1) in enumerate(bands):
            if y0 - 4 <= cy <= y1 + 4:
                words[i].append((line_key, top, left, text))
                break
    out = []
    for band_words in words:
        if not multiline:
            out.append(" ".join(w[3] for w in sorted(band_words, key=lambda w: (w[0], w[2]))))
            continue
        lines: Dict[Tuple[int, int, int], List] = defaultdict(list)
        for w in band_words:
            lines[w[0]].append(w)
        ordered = sorted(lines.values(), key=lambda ws: min(w[1] for w in ws))
        out.append("\n".join(" ".join(w[3] for w in sorted(ws, key=lambda w: w[2])) for ws in ordered))
    return out


# ============================================================================ tesseract
Runner = Callable[[List[str], bytes, float], str]

_WHITELIST = {
    "operand": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:/._[]%#",
    "digits": "0123456789",
    "block": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:/._[]%#<>()-+",
}
# (scale, binarize) variants per kind, best first; operand readings are voted across the first
# ``passes`` of them (LOGICLENS_OCR_PASSES). Measured on the PLC1 sample with +/-3 px box jitter
# (12 runs): 1 pass reads 93% of operands exactly, 3 passes 96%, 5 passes 100%; each pass is one
# tesseract call (~0.15-0.2 s for a 3-rung screenshot).
_VARIANTS = {"operand": [(6, True), (4, True), (3, False), (5, True), (8, True)], "digits": [(3, False)],
             "block": [(3, False)]}
_MAX_SHEET_CROPS = 40


def _ink_map(crop: Image.Image) -> np.ndarray:
    """Dark ink on white regardless of ink colour or theme: 255 - distance from the background."""
    a = np.asarray(crop.convert("RGB"), dtype=np.float32)
    background = np.median(a.reshape(-1, 3), axis=0)
    d = np.abs(a - background).max(axis=2)
    peak = float(d.max())
    if peak < 1:
        return np.full(d.shape, 255, dtype=np.uint8)
    return (255.0 - np.clip(d * (255.0 / peak), 0, 255)).astype(np.uint8)


def _otsu(a: np.ndarray) -> int:
    hist = np.bincount(a.ravel(), minlength=256).astype(np.float64)
    p = hist / max(hist.sum(), 1.0)
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = (mu[-1] * omega - mu) ** 2 / (omega * (1.0 - omega))
    sigma = np.nan_to_num(sigma)
    return int(np.argmax(sigma))


def _prep(ink_map: np.ndarray, scale: int, binarize: bool) -> Image.Image:
    ink = Image.fromarray(ink_map)
    ink = ink.resize((max(1, ink.width * scale), max(1, ink.height * scale)), Image.BICUBIC)
    if binarize:
        a = np.asarray(ink)
        t = _otsu(a)
        ink = Image.fromarray(np.where(a <= t, 0, 255).astype(np.uint8))
    return ink


def _sheet(crops: Sequence[Image.Image], scale: int) -> Tuple[Image.Image, List[Tuple[int, int]]]:
    pad = 12 * scale
    width = max(c.width for c in crops) + 2 * pad
    height = sum(c.height + pad for c in crops) + pad
    sheet = Image.new("L", (width, height), 255)
    bands, y = [], pad
    for c in crops:
        sheet.paste(c, (pad, y))
        bands.append((y, y + c.height))
        y += c.height + pad
    return sheet, bands


def _touching(mask: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """Ink pixels 8-connected to the seed pixels (iterative constrained dilation, vectorised)."""
    filled = seed & mask
    while True:
        grown = filled.copy()
        grown[1:, :] |= filled[:-1, :]
        grown[:-1, :] |= filled[1:, :]
        grown[:, 1:] |= filled[:, :-1]
        grown[:, :-1] |= filled[:, 1:]
        grown[1:, 1:] |= filled[:-1, :-1]
        grown[1:, :-1] |= filled[:-1, 1:]
        grown[:-1, 1:] |= filled[1:, :-1]
        grown[:-1, :-1] |= filled[1:, 1:]
        grown &= mask
        if (grown == filled).all():
            return filled
        filled = grown


def isolate_text(crop: Image.Image, symbol_edge: Optional[str]) -> np.ndarray:
    """Ink map (0 = ink, 255 = paper) of the text line nearest the symbol.

    Regions are cropped generously so a few pixels of detector jitter never clip the text; the
    price is that symbol strokes (contact brackets, the rung line) enter at the edge next to the
    symbol. Every ink component touching that edge is erased (flood fill), then the remaining ink
    is split into bands by a row projection and the band closest to the symbol is kept: that is
    the operand, descriptions sit further away."""
    raw = _ink_map(crop)
    if symbol_edge not in ("top", "bottom") or raw.shape[0] < 4:
        return raw
    # Anti-aliased strokes (thin diagonals of a '2', colons) are mid-grey: count them as ink, or a
    # glyph splits into two bands and loses its bottom bar.
    mask = raw < 200
    seed = np.zeros_like(mask)
    seed[-1 if symbol_edge == "bottom" else 0, :] = True
    for ink in (np.where(_touching(mask, seed), 255, raw).astype(np.uint8), raw):
        bands: List[List[int]] = []
        for y in np.flatnonzero((ink < 200).any(axis=1)):
            if bands and y - bands[-1][1] <= 2:  # a one-row gap stays inside a band (colons, i-dots)
                bands[-1][1] = int(y)
            else:
                bands.append([int(y), int(y)])
        text = [b for b in bands if b[1] - b[0] >= 3]
        if text:  # else: cleaning erased everything (text touching the symbol); retry on the raw map
            y0, y1 = max(text, key=lambda b: b[1]) if symbol_edge == "bottom" else min(text, key=lambda b: b[0])
            return ink[max(0, y0 - 3):min(ink.shape[0], y1 + 4), :]
    return raw


def lone_stroke(ink: np.ndarray) -> bool:
    """True when the band holds a single thin vertical stroke: a '1' in fonts that draw it as a
    bare bar, which Tesseract will not read on its own. Only used where a digit is expected."""
    mask = ink < 200
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size < 6 or cols.size == 0 or cols[-1] - cols[0] + 1 != cols.size:
        return False
    widths = mask[rows[0]:rows[-1] + 1].sum(axis=1)
    stroke = float(np.median(widths))
    height = rows[-1] - rows[0] + 1
    return 0 < stroke <= 3 and height >= 3 * stroke and cols.size <= 0.6 * height


def _subprocess_runner(argv: List[str], data: bytes, timeout: float) -> str:
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    proc = subprocess.run(argv, input=data, capture_output=True, timeout=timeout, check=False,  # nosec B603
                          env=env)
    if proc.returncode != 0:
        raise OSError(f"tesseract exited with {proc.returncode}")
    return proc.stdout.decode("utf-8", "replace")


class TesseractOcr:
    def __init__(self, cmd: str = "tesseract", timeout_s: float = 20.0, runner: Optional[Runner] = None,
                 passes: int = 5):
        self.cmd = cmd
        self.timeout_s = timeout_s
        self.passes = max(1, min(passes, len(_VARIANTS["operand"])))
        self._runner = runner or _subprocess_runner
        self._warned = False

    def available(self) -> bool:
        return shutil.which(self.cmd) is not None

    def _tsv(self, sheet: Image.Image, kind: str) -> str:
        buf = io.BytesIO()
        sheet.save(buf, format="PNG")
        argv = [self.cmd, "stdin", "stdout", "--psm", "6", "--dpi", "300",
                "-c", f"tessedit_char_whitelist={_WHITELIST[kind]}",
                "-c", "load_system_dawg=0", "-c", "load_freq_dawg=0", "tsv"]
        try:
            return self._runner(argv, buf.getvalue(), self.timeout_s)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            if not self._warned:
                log.warning("OCR unavailable or failed (%s); operands will be '?'", type(exc).__name__)
                self._warned = True
            return ""

    @staticmethod
    def _crop(image: Image.Image, region: Region) -> Optional[Image.Image]:
        x1, y1, x2, y2 = (int(round(v)) for v in region)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(image.width, x2), min(image.height, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return None
        return image.crop((x1, y1, x2, y2))

    def read(self, image: Optional[Image.Image], requests: Sequence[OcrRequest]) -> Dict[Hashable, str]:
        out: Dict[Hashable, str] = {r.key: "" for r in requests}
        if image is None or not requests:
            return out
        by_kind: Dict[str, List[Tuple[OcrRequest, np.ndarray]]] = defaultdict(list)
        for r in requests:
            crop = self._crop(image, r.region)
            if crop is not None:
                by_kind[r.kind].append((r, isolate_text(crop, r.symbol_edge)))
        for kind, items in by_kind.items():
            for start in range(0, len(items), _MAX_SHEET_CROPS):
                chunk = items[start:start + _MAX_SHEET_CROPS]
                readings: List[List[str]] = []
                for scale, binarize in _VARIANTS[kind][:self.passes]:
                    sheet, bands = _sheet([_prep(c, scale, binarize) for _, c in chunk], scale)
                    readings.append(parse_tsv(self._tsv(sheet, kind), bands, multiline=(kind == "block")))
                for i, (req, ink) in enumerate(chunk):
                    cands = [variant[i] for variant in readings]
                    if kind == "operand":
                        out[req.key] = vote(cands)
                    elif kind == "digits":
                        digits = next((re.sub(r"\D", "", c) for c in cands if re.sub(r"\D", "", c)), "")
                        out[req.key] = digits or ("1" if lone_stroke(ink) else "")
                    else:
                        out[req.key] = cands[0]
        return out


class FakeOcr:
    """Deterministic OCR for tests: returns the labels whose centre lies inside each region."""

    def __init__(self, labels: Sequence[Tuple[str, Tuple[float, float]]]):
        self.labels = list(labels)
        self.calls = 0

    def read(self, image: Optional[Image.Image], requests: Sequence[OcrRequest]) -> Dict[Hashable, str]:
        self.calls += 1
        out: Dict[Hashable, str] = {}
        for r in requests:
            x1, y1, x2, y2 = r.region
            inside = [(y, x, t) for t, (x, y) in self.labels if x1 <= x <= x2 and y1 <= y <= y2]
            inside.sort()
            sep = "\n" if r.kind == "block" else " "
            out[r.key] = sep.join(t for _, _, t in inside)
        return out
