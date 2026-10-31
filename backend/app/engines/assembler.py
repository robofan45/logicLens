"""Detections + OCR -> rungs as canonical LLT text (contract section 6 conventions).

Layout model (what ml/ renders and RSLogix screenshots show):
  * rungs are horizontal lines between the rails, top to bottom; series instructions sit on the
    rung line left to right in text order; outputs are right-aligned;
  * a parallel branch draws its first leg on the rung line and every further leg on its own row
    below, joined by a Branch_Start connector (left) and a Branch_End connector (right);
  * contact/coil operands are printed above the symbol, RSLogix 500 may split the address
    (``I:1`` above, ``1`` below); box instructions print their operands inside the rectangle.

Steps: cluster symbols into rows by y (gap clustering, so a slightly tilted photo stays one row),
read operands (one batched OCR call per kind), pair branch connectors, group rows into rungs
(rows joined by connectors; connector-less lower rows attached by layout heuristics, with a
warning), then emit each rung recursively so nested branches come out right. Unreadable operands
become ``?`` and lower the confidence. Rung texts are re-parsed by the caller (finalize_rungs);
anything the contract parser rejects is dropped with a warning there.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image

from ..program import ElementDraft, RungDraft
from ..vendor.logiclens_ladder import SPEC, classify_operand
from .base import Detection
from .ocr import Ocr, OcrRequest, box_mnemonic, join_split_address, normalize_operand, parse_box_text

CONTACT_STYLE = {"XIC", "XIO", "P", "N", "LBL", "ONS"}
COIL_STYLE = {"OTE", "NCOIL", "OTL", "OTU", "RES", "JMP"}
NO_OPERANDS = {"MCR", "END", "AFI", "NOP"}

INF = float("inf")


@dataclass
class _Sym:
    idx: int
    det: Detection
    mnemonic: str
    style: str               # contact | coil | box | none
    role: str                # in | out
    anchor_y: float = 0.0
    row: int = -1
    operands: List[str] = field(default_factory=list)
    unread: int = 0

    @property
    def cx(self) -> float:
        return self.det.cx


@dataclass
class _Branch:
    xs: float
    xe: float
    y1: float
    y2: float
    rows: List[int] = field(default_factory=list)
    implicit: bool = False
    empty_leg: bool = False
    boxes: List[Tuple[float, float, float, float]] = field(default_factory=list)

    def contains(self, other: "_Branch") -> bool:
        """A nested branch sits inside our x-range and starts on one of our legs (it may hang
        below our connectors when it is nested in the last leg)."""
        return (other is not self and other.xs >= self.xs - 1 and other.xe <= self.xe + 1
                and other.rows[0] in self.rows)


@dataclass
class AssemblyResult:
    rungs: List[RungDraft]
    warnings: List[str]


def _style(mnemonic: str) -> str:
    if mnemonic in CONTACT_STYLE:
        return "contact"
    if mnemonic in COIL_STYLE:
        return "coil"
    if mnemonic in NO_OPERANDS:
        return "none"
    return "box"


def _cluster_rows(syms: List[_Sym], gap: float) -> List[float]:
    """1-D gap clustering on anchor y. Returns row centre y per row index (top to bottom)."""
    order = sorted(syms, key=lambda s: s.anchor_y)
    rows: List[List[_Sym]] = []
    for s in order:
        if rows and s.anchor_y - rows[-1][-1].anchor_y <= gap:
            rows[-1].append(s)
        else:
            rows.append([s])
    centres = []
    for r, members in enumerate(rows):
        for s in members:
            s.row = r
        centres.append(statistics.fmean(s.anchor_y for s in members))
    return centres


class _Assembler:
    def __init__(self, image: Optional[Image.Image], detections: Sequence[Detection], ocr: Optional[Ocr]):
        self.image = image
        self.ocr = ocr
        self.warnings: List[str] = []
        self.syms = [
            _Sym(i, d, d.mnemonic, _style(d.mnemonic), SPEC[d.mnemonic][2])
            for i, d in enumerate(detections) if d.mnemonic in SPEC
        ]
        self.starts = [d for d in detections if d.structural == "branch_left"]
        self.ends = [d for d in detections if d.structural == "branch_right"]
        self.verticals = [d for d in detections if d.structural in ("branch_left", "branch_right", "rail_left",
                                                                     "rail_right")]
        small = [s.det for s in self.syms if s.style != "box"]
        self.mh = statistics.median([d.h for d in small]) if small else \
            statistics.median([s.det.h * 0.25 for s in self.syms] or [20.0])
        self.mw = statistics.median([d.w for d in small]) if small else self.mh * 1.3

    # ------------------------------------------------------------------------------- rows
    def _rows(self) -> None:
        for s in self.syms:
            if s.style == "box":
                s.anchor_y = min(s.det.cy, s.det.bbox[1] + 0.5 * self.mh)
            else:
                s.anchor_y = s.det.cy
        self.row_y = _cluster_rows(self.syms, gap=0.6 * self.mh)
        self.row_syms: Dict[int, List[_Sym]] = {}
        for s in sorted(self.syms, key=lambda s: s.cx):
            self.row_syms.setdefault(s.row, []).append(s)

    # ------------------------------------------------------------------------------- operands
    def _x_limits(self, s: _Sym, y_lo: float, y_hi: float) -> Tuple[float, float]:
        row = self.row_syms[s.row]
        k = row.index(s)
        lo = s.cx - 2.5 * s.det.w
        hi = s.cx + 2.5 * s.det.w
        if k > 0:
            lo = max(lo, (row[k - 1].cx + s.cx) / 2)
        if k + 1 < len(row):
            hi = min(hi, (row[k + 1].cx + s.cx) / 2)
        for v in self.verticals:  # never let a rail or branch connector into the crop
            if v.bbox[3] < y_lo or v.bbox[1] > y_hi:
                continue
            if v.cx <= s.det.bbox[0]:
                lo = max(lo, v.bbox[2] + 1)
            elif v.cx >= s.det.bbox[2]:
                hi = min(hi, v.bbox[0] - 1)
        return lo, hi

    def _read_operands(self) -> None:
        needs = [s for s in self.syms if s.style != "none"]
        if self.ocr is None:
            for s in self.syms:
                s.operands = ["?"] * SPEC[s.mnemonic][0]
                s.unread = len(s.operands)
            if needs:
                self.warnings.append("OCR is disabled or unavailable; operands are shown as '?'.")
            return
        requests: List[OcrRequest] = []
        for s in needs:
            x1, y1, x2, y2 = s.det.bbox
            h = s.det.h
            if s.style == "box":
                requests.append(OcrRequest((s.idx, "block"), (x1 + 2, y1 + 2, x2 - 2, y2 - 2), "block"))
                continue
            # generous on purpose: the OCR cuts the text band out (see ocr._isolate_text_band)
            top, low = y1 - 1.3 * h, y1 + 0.3 * h
            lo, hi = self._x_limits(s, top, low)
            requests.append(OcrRequest((s.idx, "above"), (lo, top, hi, low), "operand", "bottom"))
            top, low = y2 - 0.3 * h, y2 + 1.1 * h
            lo, hi = self._x_limits(s, top, low)
            requests.append(OcrRequest((s.idx, "below"), (lo, top, hi, low), "digits", "top"))
        texts = self.ocr.read(self.image, requests)
        for s in self.syms:
            lo_n, hi_n, _ = SPEC[s.mnemonic]
            if s.style == "none":
                ops: List[str] = []
            elif s.style == "box":
                text = texts.get((s.idx, "block"), "")
                said = box_mnemonic(text)
                if said and said != s.mnemonic and _style(said) == "box" and SPEC[said][2] == s.role:
                    # the header text beats the detector for boxes that only differ by their label
                    # (same role only: the rung layout was built from the detector's role)
                    s.mnemonic = said
                    lo_n, hi_n, _ = SPEC[s.mnemonic]
                ops = parse_box_text(s.mnemonic, text)
            else:
                above = normalize_operand(texts.get((s.idx, "above"), ""))
                ops = [join_split_address(above, texts.get((s.idx, "below"), ""))]
            ops = [o if o and classify_operand(o) is not None else "?" for o in ops][:hi_n]
            ops += ["?"] * (lo_n - len(ops))
            s.operands = ops
            s.unread = ops.count("?")

    # ------------------------------------------------------------------------------- branches
    def _rows_in(self, y1: float, y2: float) -> List[int]:
        tol = 0.6 * self.mh
        return [r for r, y in enumerate(self.row_y) if y1 - tol <= y <= y2 + tol]

    def _pair_connectors(self) -> List[_Branch]:
        def span_iou(a: Detection, b: Detection) -> float:
            inter = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
            union = max(a.bbox[3], b.bbox[3]) - min(a.bbox[1], b.bbox[1])
            return max(0.0, inter) / max(union, 1e-6)

        used: set = set()
        branches: List[_Branch] = []
        unpaired = 0
        for st in sorted(self.starts, key=lambda d: -d.cx):  # innermost first
            cands = [(e.cx - st.cx, k) for k, e in enumerate(self.ends)
                     if k not in used and e.cx > st.cx and span_iou(st, e) >= 0.6]
            if not cands:
                unpaired += 1
                continue
            _, k = min(cands)
            used.add(k)
            end = self.ends[k]
            y1, y2 = min(st.bbox[1], end.bbox[1]), max(st.bbox[3], end.bbox[3])
            rows = self._rows_in(y1, y2)
            if not rows:
                unpaired += 1
                continue
            b = _Branch(st.cx, end.cx, y1, y2, rows, boxes=[st.bbox, end.bbox])
            b.empty_leg = (y2 - self.row_y[rows[-1]]) > 1.5 * self.mh
            branches.append(b)
        unpaired += len(self.ends) - len(used)
        if unpaired:
            self.warnings.append(f"{unpaired} branch connector(s) could not be paired and were ignored.")
        return branches

    # ------------------------------------------------------------------------------- rungs
    def _group_rows(self, branches: List[_Branch]) -> List[List[int]]:
        parent = list(range(len(self.row_y)))

        def find(r: int) -> int:
            while parent[r] != r:
                parent[r] = parent[parent[r]]
                r = parent[r]
            return r

        for b in branches:
            for r in b.rows[1:]:
                parent[find(r)] = find(b.rows[0])
        groups: Dict[int, List[int]] = {}
        for r in range(len(self.row_y)):
            groups.setdefault(find(r), []).append(r)
        return sorted(groups.values(), key=lambda g: min(self.row_y[r] for r in g))

    def _attach_loose_rows(self, groups: List[List[int]], branches: List[_Branch]) -> List[List[int]]:
        """Connector-less lower rows: an input-only row is a parallel leg of the rung above; an
        output-only row under that rung's outputs is a parallel output."""
        result: List[List[int]] = []
        for g in groups:
            if len(g) == 1 and result:
                row = g[0]
                syms = self.row_syms[row]
                host = result[-1]
                host_main = min(host, key=lambda r: self.row_y[r])
                outputs_above = [s for r in host for s in self.row_syms[r] if s.role == "out"]
                xs = min(s.det.bbox[0] for s in syms) - 0.75 * self.mw
                xe = max(s.det.bbox[2] for s in syms) + 0.75 * self.mw
                input_leg = all(s.role == "in" for s in syms)
                output_leg = all(s.role == "out" for s in syms) and any(
                    o.det.bbox[0] < xe and o.det.bbox[2] > xs for o in outputs_above)
                if input_leg or output_leg:
                    if output_leg:
                        overlap = [o for o in outputs_above if o.det.bbox[0] < xe and o.det.bbox[2] > xs]
                        xs = min([xs] + [o.det.bbox[0] - 0.75 * self.mw for o in overlap])
                        xe = max([xe] + [o.det.bbox[2] + 0.75 * self.mw for o in overlap])
                    branches.append(_Branch(xs, xe, self.row_y[host_main], self.row_y[row], [host_main, row],
                                            implicit=True))
                    host.append(row)
                    continue
            result.append(list(g))
        return result

    def _emit(self, row: int, x_lo: float, x_hi: float, scope: List[_Branch],
              used: set) -> Tuple[str, List[ElementDraft]]:
        tops = [b for b in scope if b.rows[0] == row and x_lo - 1 <= b.xs and b.xe <= x_hi + 1]
        children = [b for b in tops if not any(o.contains(b) for o in tops)]
        items: List[Tuple[float, object]] = [(b.xs, b) for b in children]
        for s in self.row_syms.get(row, []):
            if x_lo < s.cx < x_hi and s.idx not in used and not any(c.xs < s.cx < c.xe for c in children):
                items.append((s.cx, s))
        parts: List[str] = []
        elements: List[ElementDraft] = []
        for _, item in sorted(items, key=lambda t: t[0]):
            if isinstance(item, _Sym):
                used.add(item.idx)
                parts.append(f"{item.mnemonic}({','.join(item.operands)})")
                conf = item.det.confidence * 100 * (0.6 if item.unread else 1.0)
                elements.append(ElementDraft(item.mnemonic, list(item.operands), list(item.det.bbox), conf))
                continue
            b: _Branch = item  # type: ignore[assignment]
            inner = [o for o in scope if b.contains(o)]
            interior = {r for o in inner for r in o.rows[1:]}
            legs = []
            for r in b.rows:
                if r not in interior:
                    text, els = self._emit(r, b.xs, b.xe, inner, used)
                    legs.append(text)
                    elements.extend(els)
            if b.empty_leg:
                legs.append("")
            parts.append("[" + ",".join(legs) + "]")
        return "".join(parts), elements

    def run(self) -> AssemblyResult:
        if not self.syms:
            return AssemblyResult([], ["No ladder instructions were detected in the image."])
        self._rows()
        self._read_operands()
        branches = self._pair_connectors()
        groups = self._attach_loose_rows(self._group_rows(branches), branches)
        drafts: List[RungDraft] = []
        for number, group in enumerate(groups):
            main = min(group, key=lambda r: self.row_y[r])
            scope = [b for b in branches if b.rows[0] in group]
            used: set = set()
            text, elements = self._emit(main, -INF, INF, scope, used)
            members = [s for r in group for s in self.row_syms[r]]
            confidence = statistics.fmean(e.confidence for e in elements) if elements else 0.0
            if any(b.implicit for b in scope):
                confidence *= 0.85
                self.warnings.append(f"Rung {number}: branch connectors not detected; parallel legs were "
                                     f"inferred from the layout.")
            orphans = [s for s in members if s.idx not in used]
            if orphans:
                confidence *= 0.8
                self.warnings.append(f"Rung {number}: {len(orphans)} detected instruction(s) could not be "
                                     f"placed in the rung and were ignored.")
            unread = sum(s.unread for s in members if s.idx in used)
            if unread:
                self.warnings.append(f"Rung {number}: {unread} operand(s) could not be read and are shown as '?'.")
            boxes = [s.det.bbox for s in members] + [bx for b in scope for bx in b.boxes]
            bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                    max(b[3] for b in boxes)]
            if not text:
                continue
            drafts.append(RungDraft(text=text + ";", number=number, confidence=round(confidence, 1),
                                    bbox=[round(v, 1) for v in bbox], elements=elements))
        return AssemblyResult(drafts, self.warnings)


def assemble(image: Optional[Image.Image], detections: Sequence[Detection], ocr: Optional[Ocr]) -> AssemblyResult:
    return _Assembler(image, detections, ocr).run()
