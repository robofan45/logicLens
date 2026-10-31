"""Program -> laid-out, drawn ladder diagram with tight labels (contract section 6).

Layout rules (what backend/app/engines/assembler.py assumes):
  * left/right power rails span the diagram; rungs top to bottom, rung number left of the left rail;
  * series instructions sit on the rung line in text order; outputs are right-aligned to the right
    rail, inputs start at the left rail; a parallel branch draws leg 0 on the current row and every
    further leg on its own row below, joined by a vertical connector at each end;
  * contact/coil operands are centred above the symbol (RSLogix 500: file part above, bit below);
  * a box instruction's title row is centred on the rung line, so the box top sits half a contact
    height above the line, and its mnemonic + operand rows are printed inside the rectangle.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .contract import BRANCH_END, BRANCH_START, ID_BY_MNEMONIC, RAIL_LEFT, RAIL_RIGHT, llt
from .raster import Element, Ink, rasterize, text_bbox
from .styles import FontSpec, Style
from .tags import description_for, split_slc_address

MAX_CANVAS_SIDE = 4096       # px, final image
MAX_RASTER_SIDE = 6000       # px, supersampled canvas (memory bound)

CONTACTS = {"XIC", "XIO", "P", "N", "LBL"}
COILS = {"OTE", "OTL", "OTU", "NCOIL", "RES", "JMP", "MCR", "END"}

BOX_LABELS: Dict[str, List[str]] = {
    **{m: ["Timer", "Time Base", "Preset", "Accum"] for m in ("TON", "TOF", "RTO")},
    "TP": ["Timer", "Preset", "Accum"],
    **{m: ["Counter", "Preset", "Accum"] for m in ("CTU", "CTD", "CTUD")},
    **{m: ["Source A", "Source B"] for m in ("EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ")},
    **{m: ["Source A", "Source B", "Dest"] for m in ("ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR")},
    **{m: ["Source", "Dest"] for m in ("MOV", "NOT")},
    **{m: ["Storage Bit", "Output Bit"] for m in ("OSR", "OSF")},
    "JSR": ["Routine Name"],
}
BOX_DESCRIPTIONS = {
    "TON": "Timer On Delay", "TOF": "Timer Off Delay", "RTO": "Retentive Timer On", "TP": "Timer Pulse",
    "CTU": "Count Up", "CTD": "Count Down", "CTUD": "Up/Down Counter", "EQU": "Equal", "NEQ": "Not Equal",
    "GRT": "Greater Than (A>B)", "LES": "Less Than (A<B)", "GEQ": "Grtr Than or Eql (A>=B)",
    "LEQ": "Less Than or Eql (A<=B)", "ADD": "Add", "SUB": "Subtract", "MUL": "Multiply", "DIV": "Divide",
    "MOV": "Move", "AND": "Bitwise AND", "OR": "Bitwise Inclusive OR", "XOR": "Bitwise Exclusive OR",
    "NOT": "Bitwise NOT", "OSR": "One Shot Rising", "OSF": "One Shot Falling", "JSR": "Jump To Subroutine",
}
STUBS = {"TON": ["EN", "DN"], "TOF": ["EN", "DN"], "RTO": ["EN", "DN"], "TP": ["EN", "DN"],
         "CTU": ["CU", "DN"], "CTD": ["CD", "DN"], "CTUD": ["CU", "DN"]}


def _labels_for(mnemonic: str, n_ops: int) -> List[str]:
    labels = BOX_LABELS[mnemonic]
    if mnemonic in ("TON", "TOF", "RTO") and n_ops < 4:
        labels = ["Timer", "Preset", "Accum"]
    return labels[:n_ops]


# ============================================================================== measurement


@dataclass
class Vis:
    """One instruction: its look, size and (after layout) position."""
    ins: object                      # contract Instr
    rung: int
    gidx: int
    m: str
    kind: str                        # contact | coil | box
    sym_w: float = 0.0
    sym_h: float = 0.0
    inner: str = ""
    above: List[Tuple[str, str]] = field(default_factory=list)   # (role, text) nearest first
    below: Optional[str] = None
    rows: List[Tuple[str, str, str]] = field(default_factory=list)   # (role, label, value)
    stubs: List[str] = field(default_factory=list)
    energized: bool = False
    cell_w: float = 0.0
    top: float = 0.0
    bottom: float = 0.0
    box_k: float = 0.0
    row_h: float = 0.0
    title_h: float = 0.0
    stub_w: float = 0.0
    level: int = 0
    x0: float = 0.0                  # cell left edge
    cx: float = 0.0                  # symbol centre x
    y: float = 0.0                   # rung line y of its level

    @property
    def role(self) -> str:
        return llt.SPEC[self.m][2]

    @property
    def attach_l(self) -> float:
        return self.cx - self.sym_w / 2 if self.kind == "box" else self.cx - self._attach_half()

    @property
    def attach_r(self) -> float:
        if self.kind == "box":
            return self.cx + self.sym_w / 2 + (self.stub_w if self.stubs else 0.0)
        return self.cx + self._attach_half()

    def _attach_half(self) -> float:
        return self._gap_half if self.kind == "contact" else self.sym_w / 2

    _gap_half: float = 0.0


class Measurer:
    def __init__(self, style: Style, rng: random.Random, platform: str):
        self.s = style
        self.rng = rng
        self.platform = platform
        self.ss = style.ss

    def tw(self, s: str, font: FontSpec) -> float:
        l, _, r, _ = text_bbox(s, font, self.ss)
        return r - l

    def th(self, s: str, font: FontSpec) -> Tuple[float, float]:
        """(ink top offset from baseline (negative), ink bottom offset)."""
        _, t, _, b = text_bbox(s, font, self.ss)
        return t, b

    def font_h(self, font: FontSpec) -> float:
        t, b = self.th("Ag0:/[", font)
        return b - t

    def visual(self, ins, rung: int, gidx: int) -> Vis:
        s, r = self.s, self.rng
        m = ins.mnemonic
        ops = [o.raw for o in ins.operands]
        u = s.u
        kind = "contact" if m in CONTACTS else "coil" if m in COILS else "box"
        v = Vis(ins, rung, gidx, m, kind)
        if kind != "box":
            v.energized = bool(s.highlight) and r.random() < s.highlight_rate
        if kind == "contact":
            v.inner = {"P": "P", "N": "N", "LBL": "LBL"}.get(m, "")
            inner_w = self.tw(v.inner, self._inner_font()) if v.inner else 0.0
            if s.family == "bracket":
                gap = max(s.gap, inner_w + 0.5 * u) if v.inner else s.gap
                tick = max(2.0, (s.contact_w - s.gap) / 2)
                v.sym_w = gap + 2 * tick + s.lw_sym
                v._gap_half = gap / 2
            else:
                gap = max(s.contact_w - s.lw_sym, inner_w + 0.45 * u) if v.inner else s.contact_w - s.lw_sym
                v.sym_w = gap + s.lw_sym
                v._gap_half = gap / 2
            v.sym_h = u
        elif kind == "coil":
            v.inner = {"OTL": "L" if s.family == "bracket" else "S", "OTU": "U" if s.family == "bracket" else "R",
                       "NCOIL": "/", "RES": "RES", "JMP": "JMP", "MCR": "MCR",
                       "END": "END" if s.name != "studio5000" else r.choice(["END", "End"])}.get(m, "")
            inner_w = self.tw(v.inner, self._inner_font()) if v.inner and v.inner != "/" else 0.0
            v.sym_w = max(s.coil_w, inner_w + 0.95 * u) if inner_w else s.coil_w
            v.sym_h = u * r.uniform(0.95, 1.05)
        # operand text
        if kind in ("contact", "coil") and ops:
            tag = ops[0]
            split = split_slc_address(tag) if s.split_address else None
            if split:
                v.above.append(("operand", split[0]))
                v.below = split[1]
            else:
                v.above.append(("operand", tag))
            if s.desc_rate and r.random() < s.desc_rate:
                for _ in range(r.choice([1, 1, 2])):
                    v.above.append(("desc", description_for(r, r.choice([1, 2]))))
        if kind == "box":
            self._box(v, ops)
        self._extents(v)
        return v

    def _inner_font(self) -> FontSpec:
        return FontSpec(self.s.f_op.path, max(7, int(round(self.s.u * 0.62))))

    def _box(self, v: Vis, ops: List[str]) -> None:
        s, r, u = self.s, self.rng, self.s.u
        title = s.title_aliases.get(v.m, v.m)
        v.rows.append(("title", title, ""))
        if s.name in ("rslogix500", "studio5000", "printed") or (s.name == "dark" and r.random() < 0.5):
            if r.random() < 0.85:
                v.rows.append(("desc", BOX_DESCRIPTIONS[v.m], ""))
        labels = _labels_for(v.m, len(ops))
        for label, val in zip(labels, ops):
            shown = val
            if s.lt_markers and label in ("Preset", "Accum") and r.random() < 0.9:
                shown = val + "<"
            v.rows.append(("row", label, shown))
            if s.value_lines and label.startswith(("Source", "Dest")) and llt.classify_operand(val).type == "tag":
                v.rows.append(("value", "", f"{r.choice(['0', '0', '1', '25', '100', '-3', '512'])}<"))
        if s.stubs and v.m in STUBS:
            v.stubs = list(STUBS[v.m])
        fb, ft = s.f_box, s.f_title
        hb = self.font_h(fb)
        v.row_h = hb * r.uniform(1.18, 1.45)
        v.title_h = u * r.uniform(0.9, 1.1)
        v.box_k = v.title_h / 2
        pad = max(3.0, u * r.uniform(0.25, 0.45))
        col_gap = u * r.uniform(0.6, 1.4)
        widths = []
        for role, label, val in v.rows:
            if role == "title":
                widths.append(self.tw(label, ft))
            elif role == "desc":
                widths.append(self.tw(label, fb))
            elif role == "row":
                widths.append(self.tw(label, fb) + col_gap + self.tw(val, fb))
            else:
                widths.append(self.tw(val, fb))
        v.sym_w = max(widths) + 2 * pad
        v.sym_w = max(v.sym_w, 3.2 * u)
        n_body = len(v.rows) - 1
        v.sym_h = v.title_h + n_body * v.row_h + max(2.0, 0.25 * u)
        if v.stubs:
            v.stub_w = u * 0.6 + self.tw("(EN)", fb) + u * 0.3
        v._pad = pad  # type: ignore[attr-defined]

    def _extents(self, v: Vis) -> None:
        s, u = self.s, self.s.u
        gap_t = max(1.0, 0.12 * u)
        if v.kind == "box":
            v.top = v.box_k + 0.2 * u
            v.bottom = v.sym_h - v.box_k + 0.25 * u
            v.cell_w = v.sym_w + v.stub_w + 2 * u * s.pad * 0.8
            return
        top = v.sym_h / 2
        widths = [v.sym_w]
        for i, (role, text) in enumerate(v.above):
            font = s.f_op
            t, b = self.th(text, font)
            top += (gap_t if i == 0 else max(1.0, 0.18 * u)) + (b - t)
            widths.append(self.tw(text, font))
        bottom = v.sym_h / 2
        if v.below is not None:
            t, b = self.th(v.below, s.f_op)
            bottom += max(1.0, 0.15 * u) + (b - t)
            widths.append(self.tw(v.below, s.f_op) + 2 * abs(s.bit_offset) * v.sym_w)
        v.top = top + 0.15 * u
        v.bottom = bottom + 0.15 * u
        v.cell_w = max(widths) + 2 * u * s.pad


# ============================================================================== layout


@dataclass
class BranchPlan:
    xs: float
    xe: float
    level_top: int
    level_last: int
    legs: List[Tuple[object, int]]   # (Seq, level)
    rung: int


@dataclass
class RungPlan:
    index: int                       # rung index in the image
    rung: object                     # contract Rung
    vis: List[Vis]
    branches: List[BranchPlan]
    levels: List[float] = field(default_factory=list)   # line y per level (absolute after placement)
    top: float = 0.0
    bottom: float = 0.0
    header_h: float = 0.0
    comment_lines: List[str] = field(default_factory=list)
    centered_end: bool = False


def _is_out(item) -> bool:
    if isinstance(item, llt.Instr):
        return item.role == "out"
    return any(i.role == "out" for i in llt.iter_instructions(llt.Seq([item])))


class Layout:
    def __init__(self, style: Style, vis_by_id: Dict[int, Vis]):
        self.s = style
        self.vis = vis_by_id          # id(Instr) -> Vis
        u = style.u
        self.e = 0.25 * u             # connector inset from the branch cell edge
        self.cpad = 0.3 * u           # space between a connector and the leg content
        self.min_leg = 2.2 * u        # width of an empty leg
        self.min_gap = 0.8 * u        # minimum wire between inputs and outputs

    # ---------------------------------------------------------------- widths
    def width(self, item) -> float:
        if isinstance(item, llt.Instr):
            return self.vis[id(item)].cell_w
        return 2 * (self.e + self.cpad) + max(self.seq_width(leg) for leg in item.legs)

    def seq_width(self, seq) -> float:
        items = seq.items
        if not items:
            return self.min_leg
        w = sum(self.width(i) for i in items)
        k = next((i for i, it in enumerate(items) if _is_out(it)), len(items))
        if 0 < k < len(items):
            w += self.min_gap * 0.5
        return w

    # ---------------------------------------------------------------- placement
    def place_seq(self, seq, x0: float, x1: float, level: int, branches: List[BranchPlan], rung: int) -> int:
        items = seq.items
        k = next((i for i, it in enumerate(items) if _is_out(it)), len(items))
        maxlev = level
        x = x0
        for it in items[:k]:
            maxlev = max(maxlev, self.place_item(it, x, level, branches, rung))
            x += self.width(it)
        xr = x1
        for it in reversed(items[k:]):
            xr -= self.width(it)
            maxlev = max(maxlev, self.place_item(it, xr, level, branches, rung))
        return maxlev

    def place_item(self, item, x: float, level: int, branches: List[BranchPlan], rung: int) -> int:
        if isinstance(item, llt.Instr):
            v = self.vis[id(item)]
            v.level = level
            v.x0 = x
            v.cx = x + v.cell_w / 2
            if v.kind == "box" and v.stubs:
                v.cx = x + (v.cell_w - v.stub_w) / 2
            return level
        w = self.width(item)
        xs, xe = x + self.e, x + w - self.e
        plan = BranchPlan(xs, xe, level, level, [], rung)
        branches.append(plan)
        maxlev = level
        cur = level
        for i, leg in enumerate(item.legs):
            if i > 0:
                cur = maxlev + 1
            plan.legs.append((leg, cur))
            maxlev = max(maxlev, self.place_seq(leg, xs + self.cpad, xe - self.cpad, cur, branches, rung), cur)
        plan.level_last = plan.legs[-1][1]
        return maxlev


# ============================================================================== composition


@dataclass
class TextAnno:
    role: str
    text: str
    key: str
    owner: Optional[int] = None      # global instruction index


@dataclass
class Composition:
    image: object                    # PIL.Image
    style: Style
    platform: str
    rungs: List[RungPlan]
    program_text: str                # canonical LLT of the rendered rungs (with comments)
    instructions: List[dict]         # per instruction (text order): mnemonic, class, operands, box, texts...
    structures: List[dict]           # connectors and rails
    decor: List[dict]                # rung numbers, comments, descriptions, headers...
    rung_bands: List[dict]
    size: Tuple[int, int]
    hulls: Dict[str, object]         # element key -> hull points (for augmentation)
    elements: List[Element] = field(default_factory=list)


@dataclass
class Plan:
    rungs: List[RungPlan]
    width: int
    height: int
    rail_l: float
    rail_r: float
    top_m: float
    bot_m: float
    program: str
    rung_texts: List[str]


class Composer:
    def __init__(self, style: Style, platform: str, rng: random.Random, imgsz_hint: int = 736,
                 min_eff_px: float = 14.0, canvas_scale: float = 1.0):
        self.canvas_scale = canvas_scale
        self.s = style
        self.platform = platform
        self.rng = rng
        self.imgsz = imgsz_hint
        self.min_eff = min_eff_px
        # memory bound: the supersampled canvas never exceeds MAX_RASTER_SIDE px per side
        while self.s.ss > 1 and self.max_side() * self.s.ss > MAX_RASTER_SIDE:
            self.s.ss -= 1
        self.meas = Measurer(style, rng, platform)
        self._arc_angle = rng.uniform(40.0, 56.0)
        self._arc_depth = rng.uniform(0.15, 0.24)

    # ---------------------------------------------------------------- canvas limits
    def max_side(self) -> float:
        """Longest image side keeping the smallest symbol >= min_eff px after letterboxing."""
        s = self.s
        smallest = min(s.u * 0.95, s.contact_w, s.coil_w)
        return min(MAX_CANVAS_SIDE, self.imgsz * smallest / self.min_eff * self.canvas_scale)

    # ---------------------------------------------------------------- main
    def plan(self, program_text: str, want_end: bool = False) -> Optional["Plan"]:
        s, r, u = self.s, self.rng, self.s.u
        parsed = llt.parse_program(program_text)
        if parsed.errors:
            raise ValueError(f"sampler produced an invalid program: {parsed.errors[0]}")
        cap = self.max_side()
        # rung-number column and margins
        n0 = s.rung_num_start
        num_w = 0.0
        if s.rung_label != "network":
            num_w = max(self.meas.tw(self._rung_label(n0 + i), s.f_num) for i in range(len(parsed.rungs) + 1))
        left = (num_w + u * r.uniform(0.8, 2.2) if num_w else u * r.uniform(0.8, 1.6)) + u * r.uniform(0.3, 1.0)
        if s.gutter:
            left += u * 0.4
        right_m = u * r.uniform(0.6, 2.0)
        top_m = u * r.uniform(0.6, 2.0) + (u * 1.6 if s.page_frame else 0.0)
        bot_m = u * r.uniform(0.6, 2.0) + (u * 1.4 if s.page_frame else 0.0)
        lead, lead_r = u * r.uniform(0.6, 2.4), u * r.uniform(0.6, 1.8)

        # measure all rungs
        gidx = 0
        plans: List[Tuple[object, Dict[int, Vis], float]] = []
        for k, rung in enumerate(parsed.rungs):
            vis_map: Dict[int, Vis] = {}
            for ins in llt.iter_instructions(rung.body):
                vis_map[id(ins)] = self.meas.visual(ins, k, gidx)
                gidx += 1
            lay = Layout(s, vis_map)
            need = lead + lay.seq_width(rung.body) + lay.min_gap + lead_r
            plans.append((rung, vis_map, need))
        if not plans:
            return None
        first_need = plans[0][2]
        span_target = r.uniform(0.55, 1.0) * cap - left - right_m
        span = min(cap - left - right_m, max(span_target, first_need * r.uniform(1.0, 1.25)))
        if span < first_need:
            span = min(cap - left - right_m, first_need)
        if span <= 4 * u:
            return None
        width = int(round(left + span + right_m))
        rail_l, rail_r = left, left + span

        # place rungs top to bottom while they fit
        y = top_m
        accepted: List[RungPlan] = []
        all_branches: List[BranchPlan] = []
        for rung, vis_map, need in plans:
            if need > span + 1e-6:
                continue
            rp = self._place_rung(len(accepted), rung, vis_map, rail_l, rail_r, lead, lead_r, all_branches)
            if rp is None:
                continue
            h = rp.bottom - rp.top
            if y + h + bot_m > cap and accepted:
                break
            if y + h + bot_m > cap:
                return None
            self._shift(rp, y - rp.top)
            accepted.append(rp)
            y = rp.bottom + u * s.rung_gap
        if not accepted:
            return None
        if want_end:
            end_rung = llt.parse_program("END();").rungs[0]
            vis_map = {id(i): self.meas.visual(i, len(accepted), -1) for i in llt.iter_instructions(end_rung.body)}
            rp = self._place_rung(len(accepted), end_rung, vis_map, rail_l, rail_r, lead, lead_r, all_branches,
                                  center=s.end_center)
            if rp is not None and y + (rp.bottom - rp.top) + bot_m <= cap:
                self._shift(rp, y - rp.top)
                accepted.append(rp)
                y = rp.bottom + u * s.rung_gap
        height = int(round(y - u * s.rung_gap + bot_m))
        # renumber global indices in text order of accepted rungs
        g = 0
        for rp in accepted:
            for v in rp.vis:
                v.gidx = g
                v.rung = rp.index
                g += 1
        return Plan(accepted, width, height, rail_l, rail_r, top_m, bot_m, self._program_text(accepted),
                    [rp.rung.text for rp in accepted])

    def render(self, plan: "Plan") -> Composition:
        return self._draw(plan.rungs, plan.width, plan.height, plan.rail_l, plan.rail_r, plan.top_m, plan.bot_m,
                          plan.program)

    def compose(self, program_text: str, want_end: bool = False) -> Optional[Composition]:
        plan = self.plan(program_text, want_end)
        return None if plan is None else self.render(plan)

    def _rung_label(self, n: int) -> str:
        lab = self.s.rung_label
        if lab == "rs500":
            return f"{n:04d}"
        if lab == "rung":
            return f"Rung {n}"
        return str(n)

    def _place_rung(self, index, rung, vis_map, rail_l, rail_r, lead, lead_r, all_branches, center=False):
        s, u = self.s, self.s.u
        lay = Layout(s, vis_map)
        branches: List[BranchPlan] = []
        x0, x1 = rail_l + lead, rail_r - lead_r
        vis = [vis_map[id(i)] for i in llt.iter_instructions(rung.body)]
        if center and len(vis) == 1:
            v = vis[0]
            v.level, v.cx = 0, (rail_l + rail_r) / 2
            v.x0 = v.cx - v.cell_w / 2
            maxlev = 0
        else:
            maxlev = lay.place_seq(rung.body, x0, x1, 0, branches, index)
        # inputs must not run into the right-aligned outputs
        items = rung.body.items
        k = next((i for i, it in enumerate(items) if _is_out(it)), len(items))
        if not center and x0 + sum(lay.width(i) for i in items[:k]) + lay.min_gap * 0.5 > \
                x1 - sum(lay.width(i) for i in items[k:]) + 1e-6:
            return None
        for b in branches:
            b.rung = index
        # level y positions (relative; rung line of level 0 at its top extent)
        tops = [0.8 * u] * (maxlev + 1)
        bots = [0.8 * u] * (maxlev + 1)
        for v in vis:
            tops[v.level] = max(tops[v.level], v.top)
            bots[v.level] = max(bots[v.level], v.bottom)
        rp = RungPlan(index, rung, vis, branches, centered_end=center)
        if rung.comment and s.comment_rate > 0:
            rp.comment_lines = rung.comment.split("\n")
        header = 0.0
        if s.rung_label == "network":
            header = u * 1.7 + (len(rp.comment_lines) - 1) * u * 1.1 if rp.comment_lines else u * 1.7
        elif rp.comment_lines:
            fh = self.meas.font_h(s.f_comment)
            header = len(rp.comment_lines) * fh * 1.35 + 0.4 * u
        rp.header_h = header
        levels = [header + tops[0]]
        for lv in range(1, maxlev + 1):
            levels.append(levels[-1] + bots[lv - 1] + s.vgap * u + tops[lv])
        rp.levels = levels
        rp.top = 0.0
        rp.bottom = levels[-1] + bots[-1]
        for v in vis:
            v.y = levels[v.level]
        all_branches.extend(branches)
        return rp

    @staticmethod
    def _shift(rp: RungPlan, dy: float) -> None:
        dy = float(round(dy))
        rp.levels = [y + dy for y in rp.levels]
        rp.top += dy
        rp.bottom += dy
        for v in rp.vis:
            v.y += dy

    def _program_text(self, rungs: List[RungPlan]) -> str:
        out = []
        for rp in rungs:
            if rp.rung.comment and rp.comment_lines:
                out.extend(f"// {c}" for c in rp.rung.comment.split("\n"))
            out.append(rp.rung.text)
        return "\n".join(out)

    # ================================================================ drawing
    def _draw(self, rungs: List[RungPlan], width: int, height: int, rail_l: float, rail_r: float,
              top_m: float, bot_m: float, program: str) -> Composition:
        s, r, u = self.s, self.rng, self.s.u
        rail_l, rail_r = float(round(rail_l)), float(round(rail_r))
        els: List[Element] = []
        decor_keys: List[Tuple[str, str, str]] = []   # (key, role, text)
        texts: Dict[int, List[TextAnno]] = {}

        # background decor
        if s.gutter:
            els.append(Element("gutter").rect(0, 0, rail_l - u * 0.25, height, s.gutter))
        if s.page_frame:
            self._page_frame(els, decor_keys, width, height)
        rail_top = max(1.0, top_m * r.uniform(0.25, 0.7))
        rail_bot = min(height - 1.0, height - bot_m * r.uniform(0.25, 0.7))

        for rp in rungs:
            self._draw_header(rp, els, decor_keys, rail_l, rail_r, width)

        # highlight bars and wires
        bars = Element("bars")
        wires = Element("wires")
        for rp in rungs:
            self._wires(rp, rail_l, rail_r, wires, bars)
        els.append(bars)
        els.append(wires)
        # connectors (tracked separately so their ink can be measured)
        conns: List[Tuple[str, int]] = []
        for rp in rungs:
            for bi, b in enumerate(rp.branches):
                y0, y1 = rp.levels[b.level_top], rp.levels[b.level_last]
                for side, x, cid in (("L", b.xs, BRANCH_START), ("R", b.xe, BRANCH_END)):
                    key = f"conn:{rp.index}:{bi}:{side}"
                    els.append(Element(key, track=True).vline(round(x), y0 - s.lw_wire / 2, y1 + s.lw_wire / 2,
                                                              s.lw_wire, s.wire))
                    conns.append((key, cid))
        # rails
        els.append(Element("rail:L", track=True).vline(rail_l, rail_top, rail_bot, s.lw_rail, s.rail))
        els.append(Element("rail:R", track=True).vline(rail_r, rail_top, rail_bot, s.lw_rail, s.rail))
        # symbols and their text
        for rp in rungs:
            for v in rp.vis:
                els.append(self._symbol(v))
                if v.kind == "box":
                    els.extend(self._box_extras(v, texts))
                else:
                    els.extend(self._operand_text(v, texts))
        # rung numbers
        for rp in rungs:
            if s.rung_label != "network":
                label = self._rung_label(s.rung_num_start + rp.index)
                key = f"num:{rp.index}"
                t, b = self.meas.th(label, s.f_num)
                x = rail_l - u * r.uniform(0.6, 1.6) - (u * 0.4 if s.gutter else 0)
                y = rp.levels[0] - (t + b) / 2
                els.append(Element(key, track=True).text(x, y, label, s.f_num, s.rung_num, anchor="rs"))
                decor_keys.append((key, "rung_number", label))

        img, inks = rasterize(width, height, s.ss, s.bg, els)
        return self._annotate(img, inks, rungs, conns, decor_keys, texts, width, height, program, els)

    # ---------------------------------------------------------------- pieces
    def _page_frame(self, els, decor_keys, width, height):
        s, r, u = self.s, self.rng, self.s.u
        el = Element("page", track=False)
        m = u * 0.4
        el.outline(m, m, width - m, height - m, 1, s.wire)
        els.append(el)
        title = r.choice(["LAD 2 - MAIN", "Program: MainProgram", "File #2  MAIN_PROG", "Routine: Conveyor",
                          "OB1 - Main", "PLC_PRG"])
        page = f"Page {r.randint(1, 40)}"
        f = FontSpec(s.f_comment.path, max(7, int(s.u * 0.6)))
        t, b = self.meas.th(title, f)
        key = "hdr:title"
        els.append(Element(key, track=True).text(m + u * 0.5, m + u * 0.4 - t, title, f, s.text))
        decor_keys.append((key, "page", title))
        key = "hdr:page"
        els.append(Element(key, track=True).text(width - m - u * 0.5, height - m - u * 0.4 - b, page, f, s.text, anchor="rs"))
        decor_keys.append((key, "page", page))

    def _draw_header(self, rp: RungPlan, els, decor_keys, rail_l, rail_r, width):
        s, u = self.s, self.s.u
        if rp.header_h <= 0:
            return
        y0 = rp.top
        if s.rung_label == "network":
            band_y0, band_y1 = y0 + 0.1 * u, y0 + 1.4 * u
            if s.network_band:
                els.append(Element(f"band:{rp.index}").rect(rail_l + s.lw_rail, band_y0, rail_r - s.lw_rail, band_y1,
                                                             s.network_band))
            title = f"Network {s.rung_num_start + rp.index + 1}:"
            if rp.comment_lines:
                title += " " + rp.comment_lines[0]
            t, b = self.meas.th(title, s.f_num)
            key = f"net:{rp.index}"
            els.append(Element(key, track=True).text(rail_l + u * 0.6, (band_y0 + band_y1) / 2 - (t + b) / 2, title,
                                                     s.f_num, s.rung_num))
            decor_keys.append((key, "header", title))
            for i, line in enumerate(rp.comment_lines[1:]):
                key = f"cmt:{rp.index}:{i}"
                t, b = self.meas.th(line, s.f_comment)
                yy = band_y1 + (i + 0.5) * u * 1.1 - (t + b) / 2 + 0.2 * u
                els.append(Element(key, track=True).text(rail_l + u * 0.6, yy, line, s.f_comment, s.comment))
                decor_keys.append((key, "comment", line))
            return
        fh = self.meas.font_h(s.f_comment)
        for i, line in enumerate(rp.comment_lines):
            key = f"cmt:{rp.index}:{i}"
            t, b = self.meas.th(line, s.f_comment)
            yy = y0 + (i + 1) * fh * 1.35 - b
            els.append(Element(key, track=True).text(rail_l + u * 0.5, yy, line, s.f_comment, s.comment))
            decor_keys.append((key, "comment", line))

    def _wires(self, rp: RungPlan, rail_l: float, rail_r: float, wires: Element, bars: Element) -> None:
        s, u = self.s, self.s.u
        vis_by_id = {id(v.ins): v for v in rp.vis}
        bar_h = max(3.0, u * self.rng.uniform(0.38, 0.5))
        bar_len = u * self.rng.uniform(1.4, 2.0)

        def seg(a: float, b: float, y: float, left: Optional[Vis], right: Optional[Vis]) -> None:
            if b - a <= 0.5:
                return
            wires.hline(round(a), round(b), y, s.lw_wire, s.wire)
            if s.highlight:
                if left is not None and left.energized:
                    L = min(bar_len, (b - a) * 0.45)
                    bars.rect(round(a), y - bar_h / 2, round(a + L), y + bar_h / 2, s.highlight)
                    if s.highlight_core:
                        bars.hline(round(a), round(a + L), y, 1, s.highlight_core)
                if right is not None and right.energized:
                    L = min(bar_len, (b - a) * 0.45)
                    bars.rect(round(b - L), y - bar_h / 2, round(b), y + bar_h / 2, s.highlight)
                    if s.highlight_core:
                        bars.hline(round(b - L), round(b), y, 1, s.highlight_core)

        branch_at: Dict[Tuple[int, float], BranchPlan] = {}
        for b in rp.branches:
            branch_at[(b.level_top, round(b.xs, 3))] = b

        def walk(seq, xa: float, xb: float, level: int) -> None:
            y = rp.levels[level]
            cursor, prev = xa, None
            for item in seq.items:
                if isinstance(item, llt.Instr):
                    v = vis_by_id[id(item)]
                    seg(cursor, v.attach_l, y, prev, v)
                    cursor, prev = v.attach_r, v
                else:
                    b = self._find_branch(rp, item)
                    seg(cursor, b.xs, y, prev, None)
                    for leg, lv in b.legs:
                        walk(leg, b.xs, b.xe, lv)
                    cursor, prev = b.xe, None
            seg(cursor, xb, y, prev, None)

        walk(rp.rung.body, rail_l, rail_r, 0)

    def _find_branch(self, rp: RungPlan, item) -> BranchPlan:
        for b in rp.branches:
            if b.legs and b.legs[0][0] is item.legs[0]:
                return b
        raise KeyError("branch plan not found")  # pragma: no cover

    # ---------------------------------------------------------------- symbols
    def _symbol(self, v: Vis) -> Element:
        s = self.s
        el = Element(f"sym:{v.gidx}", track=True)
        cx, cy = round(v.cx), v.y
        lw = s.lw_sym
        col = s.symbol
        if v.kind == "contact":
            h = v.sym_h
            gh = v._gap_half
            y0, y1 = cy - h / 2, cy + h / 2
            xl, xr = round(cx - gh), round(cx + gh)
            if s.family == "bracket":
                tick = max(2.0, (v.sym_w - 2 * gh - lw) / 2)
                for x, d in ((xl, -1), (xr, 1)):
                    el.vline(x, y0, y1, lw, col)
                    el.hline(x, x + d * (tick + lw / 2), y0 + lw / 2, lw, col)
                    el.hline(x, x + d * (tick + lw / 2), y1 - lw / 2, lw, col)
                ext_l, ext_r = xl - tick, xr + tick
            else:
                el.vline(xl, y0, y1, lw, col)
                el.vline(xr, y0, y1, lw, col)
                ext_l, ext_r = xl - lw / 2, xr + lw / 2
            if v.m == "XIO":
                if s.family == "bracket":
                    el.line([(ext_l + lw * 0.5, y1 - lw * 0.3), (ext_r - lw * 0.5, y0 + lw * 0.3)], max(1, lw), col)
                else:
                    el.line([(xl + lw * 0.3, y1 - lw * 0.3), (xr - lw * 0.3, y0 + lw * 0.3)], max(1, lw), col)
            elif v.inner:
                f = self.meas._inner_font()
                t, b = self.meas.th(v.inner, f)
                el.text(cx, cy - (t + b) / 2, v.inner, f, col, anchor="ms")
            return el
        if v.kind == "coil":
            h, w = v.sym_h, v.sym_w
            y0, y1 = cy - h / 2, cy + h / 2
            xl, xr = cx - w / 2, cx + w / 2
            if s.coil_shape == "chevron":
                depth = min(w * 0.3, h * 0.5)
                el.line([(xl + depth, y0), (xl, cy), (xl + depth, y1)], lw, col)
                el.line([(xr - depth, y0), (xr, cy), (xr - depth, y1)], lw, col)
            else:
                a = self._arc_angle
                ry = (h / 2) / math.sin(math.radians(a))
                depth = min(w * self._arc_depth, h * 0.4)
                rx = depth / (1 - math.cos(math.radians(a)))
                el.arc((xl, cy - ry, xl + 2 * rx, cy + ry), 180 - a, 180 + a, lw, col)
                el.arc((xr - 2 * rx, cy - ry, xr, cy + ry), -a, a, lw, col)
            if v.inner == "/":
                el.line([(cx - w * 0.14, y1 - h * 0.18), (cx + w * 0.14, y0 + h * 0.18)], max(1, lw), col)
            elif v.inner:
                f = self.meas._inner_font()
                t, b = self.meas.th(v.inner, f)
                el.text(cx, cy - (t + b) / 2, v.inner, f, col, anchor="ms")
            return el
        # box: rectangle + header + text inside
        x0 = round(v.cx - v.sym_w / 2)
        x1 = round(v.cx + v.sym_w / 2)
        y0 = round(cy - v.box_k)
        y1 = round(y0 + v.sym_h)
        if s.box_fill:
            el.rect(x0, y0, x1, y1, s.box_fill)
        if s.box_header:
            el.rect(x0, y0, x1, y0 + v.title_h, s.box_header)
        lwb = s.lw_box
        el.hline(x0 - lwb / 2, x1 + lwb / 2, y0, lwb, s.box_stroke)
        el.hline(x0 - lwb / 2, x1 + lwb / 2, y1, lwb, s.box_stroke)
        el.vline(x0, y0, y1, lwb, s.box_stroke)
        el.vline(x1, y0, y1, lwb, s.box_stroke)
        if s.box_header or s.name == "tia":
            el.hline(x0, x1, y0 + v.title_h, max(1, lwb), s.box_stroke)
        return el

    def _box_extras(self, v: Vis, texts: Dict[int, List[TextAnno]]) -> List[Element]:
        """Text inside a box (separately tracked so the metadata has its boxes) and EN/DN stubs."""
        s, u = self.s, self.s.u
        out: List[Element] = []
        x0 = round(v.cx - v.sym_w / 2)
        x1 = round(v.cx + v.sym_w / 2)
        y0 = round(v.y - v.box_k)
        pad = getattr(v, "_pad", 0.3 * u)
        anns = texts.setdefault(v.gidx, [])
        row_y = y0 + v.title_h  # top of the first body row
        for i, (role, label, val) in enumerate(v.rows):
            key = f"btx:{v.gidx}:{i}"
            el = Element(key, track=True)
            if role == "title":
                f = s.f_title
                t, b = self.meas.th(label, f)
                yb = y0 + v.title_h / 2 - (t + b) / 2
                if s.title_align == "center":
                    el.text((x0 + x1) / 2, yb, label, f, s.box_title, anchor="ms")
                else:
                    el.text(x0 + pad, yb, label, f, s.box_title)
                anns.append(TextAnno("box_title", label, key, v.gidx))
            else:
                f = s.f_box
                t, b = self.meas.th("Ag0", f)
                yb = row_y + v.row_h / 2 - (t + b) / 2
                if role == "desc":
                    el.text(x0 + pad, yb, label, f, s.box_text)
                    anns.append(TextAnno("box_desc", label, key, v.gidx))
                elif role == "value":
                    el.text(x1 - pad, yb, val, f, s.box_text, anchor="rs")
                    anns.append(TextAnno("box_value", val, key, v.gidx))
                else:
                    el.text(x0 + pad, yb, label, f, s.box_text)
                    if s.name in ("rslogix500", "printed", "dark") or s.title_align == "left" and s.name != "tia":
                        el.text(x1 - pad, yb, val, f, s.box_text, anchor="rs")
                    else:
                        lw_ = self.meas.tw(label, f)
                        el.text(x0 + pad + lw_ + u * 0.8, yb, val, f, s.box_text)
                    anns.append(TextAnno("box_row", f"{label} {val}", key, v.gidx))
                row_y += v.row_h
            out.append(el)
        if v.stubs:
            el = Element(f"stub:{v.gidx}", track=True)
            f = s.f_box
            n_body = len(v.rows) - 1
            dn_y = y0 + v.title_h + v.row_h * (min(2, max(1, n_body)) - 0.5)
            for k, name in enumerate(v.stubs):
                yy = v.y if k == 0 else dn_y
                b = x1 + u * 0.6
                el.hline(x1, b, yy, s.lw_wire, s.wire)
                t, bb = self.meas.th(f"({name})", f)
                el.text(b, yy - (t + bb) / 2, f"({name})", f, s.box_stroke)
                tw = self.meas.tw(f"({name})", f)
                tail = (x1 + v.stub_w) if k == 0 else (b + tw + u * 0.3)
                if tail > b + tw:
                    el.hline(b + tw, tail, yy, s.lw_wire, s.wire)
            out.append(el)
            anns.append(TextAnno("stub", " ".join(v.stubs), f"stub:{v.gidx}", v.gidx))
        return out

    def _operand_text(self, v: Vis, texts: Dict[int, List[TextAnno]]) -> List[Element]:
        s, u = self.s, self.s.u
        out: List[Element] = []
        anns = texts.setdefault(v.gidx, [])
        cx = round(v.cx)
        y_top = v.y - v.sym_h / 2
        cursor = y_top - max(1.0, 0.12 * u)       # ink bottom of the next line above
        for i, (role, text) in enumerate(v.above):
            font = s.f_op
            t, b = self.meas.th(text, font)
            key = f"txt:{v.gidx}:{i}"
            color = s.text if role == "operand" else s.desc_text
            out.append(Element(key, track=True).text(cx, cursor - b, text, font, color, anchor="ms"))
            anns.append(TextAnno(role, text, key, v.gidx))
            cursor = cursor - (b - t) - max(1.0, 0.18 * u)
        if v.below is not None:
            font = s.f_op
            t, b = self.meas.th(v.below, font)
            key = f"txt:{v.gidx}:bit"
            yb = v.y + v.sym_h / 2 + max(1.0, 0.15 * u) - t
            out.append(Element(key, track=True).text(cx + s.bit_offset * v.sym_w, yb, v.below, font, s.text, anchor="ms"))
            anns.append(TextAnno("bit", v.below, key, v.gidx))
        return out

    # ---------------------------------------------------------------- annotations
    def _annotate(self, img, inks: Dict[str, Ink], rungs, conns, decor_keys, texts, width, height, program, els):
        s, u = self.s, self.s.u
        hulls: Dict[str, object] = {}
        instructions: List[dict] = []
        for rp in rungs:
            for k, v in enumerate(rp.vis):
                ink = inks[f"sym:{v.gidx}"]
                hulls[f"sym:{v.gidx}"] = ink.hull
                tx = []
                for a in texts.get(v.gidx, []):
                    ti = inks.get(a.key)
                    if ti is None:
                        continue
                    hulls[a.key] = ti.hull
                    tx.append({"role": a.role, "text": a.text, "box": list(ti.box), "key": a.key})
                instructions.append({
                    "rung": rp.index, "index": k, "id": f"r{rp.index}i{k}", "mnemonic": v.m,
                    "class_id": ID_BY_MNEMONIC[v.m], "operands": [o.raw for o in v.ins.operands],
                    "kind": v.kind, "row": v.level, "line_y": v.y, "box": list(ink.box), "key": f"sym:{v.gidx}",
                    "energized": v.energized, "texts": tx, "visible": True,
                })
        structures: List[dict] = []
        min_w = 6.0
        for key, cid in conns:
            ink = inks[key]
            x0, y0, x1, y1 = ink.box
            half = max(min_w / 2, (x1 - x0) / 2 + 2)
            cxm = (x0 + x1) / 2
            box = [max(0.0, cxm - half), max(0.0, y0 - 2), min(float(width), cxm + half), min(float(height), y1 + 2)]
            hulls[key] = _rect_hull(box)
            structures.append({"class_id": cid, "box": box, "key": key, "rung": int(key.split(":")[1])})
        for key, cid in (("rail:L", RAIL_LEFT), ("rail:R", RAIL_RIGHT)):
            ink = inks[key]
            x0, y0, x1, y1 = ink.box
            half = max(min_w / 2 + 0.5, (x1 - x0) / 2 + 2)
            cxm = (x0 + x1) / 2
            box = [max(0.0, cxm - half), y0, min(float(width), cxm + half), y1]
            hulls[key] = _rect_hull(box)
            structures.append({"class_id": cid, "box": box, "key": key, "rung": None})
        decor = []
        for key, role, text in decor_keys:
            ink = inks.get(key)
            if ink is not None:
                hulls[key] = ink.hull
                decor.append({"role": role, "text": text, "box": list(ink.box), "key": key})
        for v_list in texts.values():
            pass
        bands = []
        for rp in rungs:
            boxes = [i["box"] for i in instructions if i["rung"] == rp.index]
            boxes += [t["box"] for i in instructions if i["rung"] == rp.index for t in i["texts"]]
            boxes += [st["box"] for st in structures if st["rung"] == rp.index]
            boxes += [d["box"] for d in decor if d["key"].split(":")[0] in ("cmt", "net", "num")
                      and d["key"].split(":")[1] == str(rp.index)]
            band = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
            bands.append({"rung": rp.index, "band": band, "line_y": rp.levels[0]})
            hulls[f"band:{rp.index}"] = _rect_hull(band)
        return Composition(img, s, self.platform, rungs, program, instructions, structures, decor, bands,
                           (width, height), hulls, els)


def _rect_hull(box) -> "object":
    import numpy as np
    x0, y0, x1, y1 = box
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
