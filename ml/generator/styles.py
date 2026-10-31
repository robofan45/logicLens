"""Visual styles: colours, fonts, stroke widths and symbol geometry, sampled per image.

Six families:
  rslogix500  RSLogix 500 look (samples/ladder_logic_program_PLC1.webp): purple rails/symbols,
              ``] [`` contacts, chevron coils, serif addresses split above/below, green energized bars.
  studio5000  Studio 5000 look: black on white, tag names above, round coils, grey rung-number gutter.
  tia         TIA-Portal/IEC look: ``| |`` contacts, round coils, network header bands, box headers.
  iec         Generic IEC 61131-3 editor (CODESYS-like): ``| |`` contacts, sans fonts, coloured boxes.
  printed     Black-on-white printout: either family, page header/footer, serif or mono text.
  dark        Dark IDE theme: light strokes on a dark background, coloured symbols.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

RGB = Tuple[int, int, int]
STYLES = ("rslogix500", "studio5000", "tia", "iec", "printed", "dark")
STYLE_WEIGHTS = {"rslogix500": 0.30, "studio5000": 0.20, "tia": 0.15, "iec": 0.12, "printed": 0.12, "dark": 0.11}

_FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
              "/Library/Fonts", "C:/Windows/Fonts"]
_FONT_CANDIDATES: Dict[str, List[str]] = {
    "serif": ["LiberationSerif-Regular.ttf", "FreeSerif.ttf", "DejaVuSerif.ttf", "Caladea-Regular.ttf",
              "times.ttf"],
    "serif_bold": ["LiberationSerif-Bold.ttf", "FreeSerifBold.ttf", "DejaVuSerif-Bold.ttf", "timesbd.ttf"],
    "sans": ["LiberationSans-Regular.ttf", "DejaVuSans.ttf", "FreeSans.ttf", "Carlito-Regular.ttf",
             "Inter-Regular.otf", "arial.ttf", "segoeui.ttf", "tahoma.ttf"],
    "sans_bold": ["LiberationSans-Bold.ttf", "DejaVuSans-Bold.ttf", "FreeSansBold.ttf", "Carlito-Bold.ttf",
                  "Inter-Bold.otf", "arialbd.ttf"],
    "condensed": ["DejaVuSansCondensed.ttf", "LiberationSansNarrow-Regular.ttf", "Carlito-Regular.ttf"],
    "mono": ["LiberationMono-Regular.ttf", "DejaVuSansMono.ttf", "FreeMono.ttf", "cour.ttf", "consola.ttf"],
    "mono_bold": ["LiberationMono-Bold.ttf", "DejaVuSansMono-Bold.ttf", "FreeMonoBold.ttf"],
}


@lru_cache(maxsize=1)
def _font_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for d in _FONT_DIRS:
        p = Path(d)
        if not p.is_dir():
            continue
        for f in sorted(p.rglob("*")):
            if f.suffix.lower() in (".ttf", ".otf") and f.name not in index:
                index[f.name] = str(f)
    return index


def font_paths(kind: str) -> List[str]:
    """Available font files of a kind, in a fixed order (determinism per machine)."""
    idx = _font_index()
    return [idx[n] for n in _FONT_CANDIDATES[kind] if n in idx]


@dataclass(frozen=True)
class FontSpec:
    path: Optional[str]   # None -> Pillow's built-in font
    px: int

    def load(self, ss: int = 1):
        return _load_font(self.path, self.px * ss)


@lru_cache(maxsize=512)
def _load_font(path: Optional[str], size: int):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def pick_font(rng: random.Random, kinds: List[str], px: float) -> FontSpec:
    for kind in kinds:
        paths = font_paths(kind)
        if paths:
            return FontSpec(rng.choice(paths), max(7, int(round(px))))
    return FontSpec(None, max(7, int(round(px))))


@dataclass
class Style:
    name: str
    family: str                      # "bracket" (] [) or "bar" (| |)
    ss: int                          # supersampling factor (1 = aliased GDI-like strokes)
    bg: RGB
    wire: RGB
    rail: RGB
    symbol: RGB
    text: RGB
    desc_text: RGB
    rung_num: RGB
    comment: RGB
    box_stroke: RGB
    box_text: RGB
    box_title: RGB
    box_fill: Optional[RGB]
    box_header: Optional[RGB]
    highlight: Optional[RGB]
    highlight_core: Optional[RGB]
    highlight_rate: float
    u: int                           # contact height in px (the symbol unit)
    contact_w: int
    coil_w: int
    coil_shape: str                  # chevron | arc
    gap: int                         # gap between the two strokes of a contact
    tick: int                        # bracket tick length (bracket family)
    lw_wire: int
    lw_sym: int
    lw_box: int
    lw_rail: int
    f_op: FontSpec
    f_box: FontSpec
    f_title: FontSpec
    f_num: FontSpec
    f_comment: FontSpec
    split_address: bool
    desc_rate: float
    rung_label: str                  # rs500 | plain | network | rung
    rung_num_start: int
    comment_rate: float
    stubs: bool
    value_lines: bool
    lt_markers: bool
    title_align: str                 # left | center
    end_center: bool
    gutter: Optional[RGB]
    network_band: Optional[RGB]
    page_frame: bool
    pad: float                       # horizontal padding per cell, in u
    vgap: float                      # vertical gap between rows, in u
    rung_gap: float                  # vertical gap between rungs, in u
    title_aliases: Dict[str, str] = field(default_factory=dict)
    bit_offset: float = 0.0          # RSLogix 500 bit number sits right of centre (in symbol widths)


def _jitter(rng: random.Random, c: RGB, amount: int) -> RGB:
    return tuple(max(0, min(255, v + rng.randint(-amount, amount))) for v in c)  # type: ignore[return-value]


def sample_style(name: str, rng: random.Random, platform: str) -> Style:
    """Sample one concrete style of a family. ``platform`` decides the symbol family for the
    platform-neutral families (printed, dark)."""
    if name not in STYLES:
        raise ValueError(f"unknown style {name!r}")
    r = rng
    u = int(round(r.choice([r.uniform(14, 20), r.uniform(14, 24), r.uniform(16, 30)])))
    rockwell = platform.startswith("rockwell")
    family = "bracket" if rockwell else "bar"
    if name in ("rslogix500", "studio5000"):
        family = "bracket"
    elif name in ("tia", "iec"):
        family = "bar"
    lw = 1 if u < 18 else r.choice([1, 2, 2])
    common = dict(family=family, u=u, lw_wire=lw, lw_sym=max(1, lw + r.choice([0, 0, 1]) - (1 if u < 16 else 0)),
                  lw_box=lw, lw_rail=max(1, lw + r.choice([0, 0, 1])), rung_num_start=r.choice([0] * 5 + [r.randint(1, 60)]),
                  bit_offset=0.0, title_aliases={})
    if family == "bracket":
        gap = int(round(u * r.uniform(0.5, 0.75)))
        tick = max(2, int(round(u * r.uniform(0.22, 0.38))))
        common.update(contact_w=gap + 2 * tick + 1, gap=gap, tick=tick)
    else:
        common.update(contact_w=int(round(u * r.uniform(0.85, 1.25))), gap=int(round(u * r.uniform(0.55, 0.85))),
                      tick=0)
    common["coil_w"] = int(round(u * r.uniform(1.45, 1.85)))

    if name == "rslogix500":
        purple = _jitter(r, r.choice([(153, 102, 204), (160, 110, 230), (140, 90, 210), (170, 120, 220)]), 12)
        hl = r.random() < 0.6
        s = Style(name=name, ss=r.choice([1, 1, 2]), bg=(255, 255, 255), wire=purple, rail=purple, symbol=purple,
                  text=_jitter(r, (30, 30, 30), 25), desc_text=(20, 20, 20), rung_num=_jitter(r, (106, 42, 157), 15),
                  comment=(0, 0, 0), box_stroke=purple, box_text=(20, 20, 20), box_title=(20, 20, 20), box_fill=None,
                  box_header=None, highlight=(0, 255, 0) if hl else None, highlight_core=(20, 120, 20),
                  highlight_rate=r.uniform(0.3, 0.8), coil_shape="chevron",
                  f_op=pick_font(r, ["serif"], u * r.uniform(0.8, 0.95)),
                  f_box=pick_font(r, ["serif"], u * r.uniform(0.75, 0.9)),
                  f_title=pick_font(r, ["serif"], u * r.uniform(0.8, 0.95)),
                  f_num=pick_font(r, ["serif", "serif_bold"], u * r.uniform(0.8, 0.95)),
                  f_comment=pick_font(r, ["serif", "sans"], u * r.uniform(0.75, 0.9)),
                  split_address=r.random() < 0.9, desc_rate=r.choice([0.0, 0.0, 0.0, 0.5, 0.9]), rung_label="rs500",
                  comment_rate=r.choice([0.0, 0.0, 0.3, 0.6]), stubs=r.random() < 0.85, value_lines=r.random() < 0.6,
                  lt_markers=r.random() < 0.7, title_align="left", end_center=True, gutter=None, network_band=None,
                  page_frame=False, pad=r.uniform(0.55, 1.1), vgap=r.uniform(0.8, 1.6), rung_gap=r.uniform(1.0, 3.0),
                  **common)
        s.bit_offset = r.uniform(0.1, 0.3)
        return s
    if name == "studio5000":
        ink = _jitter(r, (0, 0, 0), 30)
        s = Style(name=name, ss=r.choice([1, 2, 2]), bg=(255, 255, 255), wire=ink, rail=_jitter(r, (40, 40, 40), 20),
                  symbol=ink, text=(0, 0, 0), desc_text=r.choice([(0, 128, 0), (0, 0, 160), (90, 90, 90)]),
                  rung_num=(0, 0, 0), comment=r.choice([(0, 128, 0), (0, 0, 0)]), box_stroke=ink, box_text=(0, 0, 0),
                  box_title=(0, 0, 0), box_fill=None, box_header=r.choice([None, (230, 230, 230)]),
                  highlight=(0, 200, 0) if r.random() < 0.4 else None, highlight_core=None,
                  highlight_rate=r.uniform(0.3, 0.7), coil_shape="arc",
                  f_op=pick_font(r, ["sans"], u * r.uniform(0.62, 0.8)),
                  f_box=pick_font(r, ["sans"], u * r.uniform(0.6, 0.75)),
                  f_title=pick_font(r, ["sans_bold", "sans"], u * r.uniform(0.65, 0.8)),
                  f_num=pick_font(r, ["sans"], u * r.uniform(0.65, 0.8)),
                  f_comment=pick_font(r, ["sans"], u * r.uniform(0.6, 0.75)),
                  split_address=False, desc_rate=r.choice([0.0, 0.0, 0.4, 0.8]), rung_label="plain",
                  comment_rate=r.choice([0.0, 0.3, 0.6]), stubs=r.random() < 0.9, value_lines=False,
                  lt_markers=False, title_align="left", end_center=True,
                  gutter=r.choice([(235, 235, 235), (225, 228, 235), None]), network_band=None, page_frame=False,
                  pad=r.uniform(0.6, 1.2), vgap=r.uniform(0.8, 1.6), rung_gap=r.uniform(1.0, 2.5), **common)
        return s
    if name == "tia":
        ink = _jitter(r, (0, 0, 0), 20)
        s = Style(name=name, ss=r.choice([2, 2, 3]), bg=r.choice([(255, 255, 255), (250, 250, 250)]), wire=ink,
                  rail=ink, symbol=ink, text=(0, 0, 0), desc_text=(80, 80, 80), rung_num=(0, 0, 0), comment=(0, 0, 0),
                  box_stroke=_jitter(r, (60, 60, 60), 20), box_text=(0, 0, 0), box_title=(0, 0, 0),
                  box_fill=r.choice([None, (255, 255, 255), (245, 248, 252)]),
                  box_header=r.choice([None, (210, 225, 240), (225, 225, 225)]),
                  highlight=r.choice([None, None, (0, 220, 0)]), highlight_core=None, highlight_rate=r.uniform(0.3, 0.7),
                  coil_shape="arc", f_op=pick_font(r, ["sans", "condensed"], u * r.uniform(0.6, 0.75)),
                  f_box=pick_font(r, ["sans", "condensed"], u * r.uniform(0.58, 0.72)),
                  f_title=pick_font(r, ["sans_bold"], u * r.uniform(0.62, 0.78)),
                  f_num=pick_font(r, ["sans_bold", "sans"], u * r.uniform(0.62, 0.78)),
                  f_comment=pick_font(r, ["sans"], u * r.uniform(0.58, 0.72)),
                  split_address=False, desc_rate=r.choice([0.0, 0.0, 0.4]), rung_label="network",
                  comment_rate=r.choice([0.3, 0.6, 0.9]), stubs=False, value_lines=False, lt_markers=False,
                  title_align="center", end_center=False, gutter=None,
                  network_band=r.choice([(232, 232, 232), (225, 230, 238), None]), page_frame=False,
                  pad=r.uniform(0.6, 1.2), vgap=r.uniform(0.8, 1.5), rung_gap=r.uniform(1.0, 2.2), **common)
        s.title_aliases = {"RTO": "TONR", "MOV": "MOVE", "NOT": "INV"} if r.random() < 0.6 else {}
        return s
    if name == "iec":
        pal = r.choice([((0, 0, 0), (0, 70, 160)), ((40, 40, 40), (0, 110, 70)), ((0, 0, 0), (0, 0, 0)),
                        ((20, 20, 90), (150, 30, 30))])
        s = Style(name=name, ss=r.choice([1, 2, 3]), bg=r.choice([(255, 255, 255), (252, 252, 246), (246, 248, 250)]),
                  wire=pal[0], rail=pal[0], symbol=pal[1], text=(0, 0, 0), desc_text=(90, 90, 90), rung_num=(60, 60, 60),
                  comment=(0, 110, 0), box_stroke=pal[1], box_text=(0, 0, 0), box_title=pal[1],
                  box_fill=r.choice([None, (255, 255, 230), (235, 245, 255)]), box_header=None,
                  highlight=r.choice([None, None, (60, 200, 60)]), highlight_core=None,
                  highlight_rate=r.uniform(0.3, 0.7), coil_shape="arc",
                  f_op=pick_font(r, ["sans", "mono", "condensed"], u * r.uniform(0.6, 0.8)),
                  f_box=pick_font(r, ["sans", "mono"], u * r.uniform(0.58, 0.75)),
                  f_title=pick_font(r, ["sans_bold", "mono_bold"], u * r.uniform(0.62, 0.8)),
                  f_num=pick_font(r, ["sans", "mono"], u * r.uniform(0.6, 0.78)),
                  f_comment=pick_font(r, ["sans"], u * r.uniform(0.58, 0.75)),
                  split_address=False, desc_rate=0.0, rung_label=r.choice(["plain", "rung"]),
                  comment_rate=r.choice([0.0, 0.3, 0.6]), stubs=False, value_lines=False, lt_markers=False,
                  title_align=r.choice(["left", "center"]), end_center=False, gutter=None, network_band=None,
                  page_frame=False, pad=r.uniform(0.6, 1.2), vgap=r.uniform(0.8, 1.6), rung_gap=r.uniform(1.0, 2.5),
                  **common)
        return s
    if name == "printed":
        ink = _jitter(r, (10, 10, 10), 10)
        paper = r.choice([(255, 255, 255), (250, 249, 244), (246, 244, 236)])
        kinds = r.choice([["serif"], ["mono"], ["sans"]])
        s = Style(name=name, ss=r.choice([2, 3]), bg=paper, wire=ink, rail=ink, symbol=ink, text=ink, desc_text=ink,
                  rung_num=ink, comment=ink, box_stroke=ink, box_text=ink, box_title=ink, box_fill=None, box_header=None,
                  highlight=None, highlight_core=None, highlight_rate=0.0,
                  coil_shape="chevron" if (family == "bracket" and r.random() < 0.4) else "arc",
                  f_op=pick_font(r, kinds, u * r.uniform(0.62, 0.85)),
                  f_box=pick_font(r, kinds, u * r.uniform(0.6, 0.8)),
                  f_title=pick_font(r, [kinds[0] + "_bold", kinds[0]], u * r.uniform(0.65, 0.85)),
                  f_num=pick_font(r, kinds, u * r.uniform(0.65, 0.85)),
                  f_comment=pick_font(r, kinds, u * r.uniform(0.6, 0.8)),
                  split_address=(platform == "rockwell_slc" and r.random() < 0.8),
                  desc_rate=r.choice([0.0, 0.3, 0.7]), rung_label=r.choice(["rs500", "rung", "plain"]),
                  comment_rate=r.choice([0.0, 0.4, 0.8]), stubs=rockwell and r.random() < 0.6,
                  value_lines=False, lt_markers=False, title_align=r.choice(["left", "center"]),
                  end_center=rockwell, gutter=None, network_band=None, page_frame=r.random() < 0.6,
                  pad=r.uniform(0.6, 1.2), vgap=r.uniform(0.8, 1.6), rung_gap=r.uniform(1.0, 2.5), **common)
        s.bit_offset = r.uniform(0.0, 0.25) if s.split_address else 0.0
        return s
    # dark
    bg = r.choice([(30, 30, 30), (37, 37, 38), (43, 43, 43), (24, 26, 33), (40, 44, 52)])
    wire = r.choice([(200, 200, 200), (170, 170, 170), (120, 200, 255)])
    sym = r.choice([(220, 220, 170), (156, 220, 254), (255, 198, 109), (230, 230, 230)])
    s = Style(name=name, ss=r.choice([1, 2, 2]), bg=bg, wire=wire, rail=wire, symbol=sym,
              text=r.choice([(212, 212, 212), (230, 230, 230)]), desc_text=(140, 160, 140), rung_num=(133, 133, 133),
              comment=(106, 153, 85), box_stroke=r.choice([(197, 134, 192), sym, wire]), box_text=(212, 212, 212),
              box_title=r.choice([(86, 156, 214), (220, 220, 170), (255, 255, 255)]),
              box_fill=r.choice([None, (45, 45, 48), (50, 54, 62)]), box_header=r.choice([None, (62, 62, 66)]),
              highlight=r.choice([None, (78, 201, 78)]), highlight_core=None, highlight_rate=r.uniform(0.3, 0.7),
              coil_shape="arc" if family == "bar" or r.random() < 0.6 else "chevron",
              f_op=pick_font(r, ["mono", "sans"], u * r.uniform(0.6, 0.8)),
              f_box=pick_font(r, ["mono", "sans"], u * r.uniform(0.58, 0.75)),
              f_title=pick_font(r, ["mono_bold", "sans_bold"], u * r.uniform(0.62, 0.8)),
              f_num=pick_font(r, ["mono", "sans"], u * r.uniform(0.6, 0.78)),
              f_comment=pick_font(r, ["mono", "sans"], u * r.uniform(0.58, 0.75)),
              split_address=(platform == "rockwell_slc" and r.random() < 0.7), desc_rate=0.0,
              rung_label=r.choice(["plain", "rung", "rs500"]), comment_rate=r.choice([0.0, 0.3, 0.6]),
              stubs=rockwell and r.random() < 0.5, value_lines=False, lt_markers=False,
              title_align=r.choice(["left", "center"]), end_center=rockwell, gutter=None, network_band=None,
              page_frame=False, pad=r.uniform(0.6, 1.2), vgap=r.uniform(0.8, 1.6), rung_gap=r.uniform(1.0, 2.5), **common)
    s.bit_offset = r.uniform(0.0, 0.25) if s.split_address else 0.0
    return s


# Which tag style (platform) goes with which visual family.
PLATFORM_BY_STYLE = {
    "rslogix500": {"rockwell_slc": 1.0},
    "studio5000": {"rockwell_logix": 1.0},
    "tia": {"siemens_tia": 1.0},
    "iec": {"generic_iec": 0.7, "siemens_tia": 0.3},
    "printed": {"rockwell_slc": 0.3, "rockwell_logix": 0.3, "generic_iec": 0.2, "siemens_tia": 0.2},
    "dark": {"rockwell_logix": 0.35, "generic_iec": 0.35, "siemens_tia": 0.2, "rockwell_slc": 0.1},
}


def choose_style_and_platform(rng: random.Random) -> Tuple[str, str]:
    names = list(STYLE_WEIGHTS)
    name = rng.choices(names, [STYLE_WEIGHTS[n] for n in names])[0]
    plats = PLATFORM_BY_STYLE[name]
    platform = rng.choices(list(plats), list(plats.values()))[0]
    return name, platform
