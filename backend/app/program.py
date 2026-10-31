"""Turn engine output (or pasted text) into contract Program JSON.

Every rung text that leaves the backend has been re-parsed by the vendored contract parser and is
printed canonically; anything that does not parse is dropped with a warning. ``elements[i]`` is
aligned with the i-th instruction of the rung in text order and only carries overlay data.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from . import __version__
from .errors import ApiError
from .schemas import Element, EngineInfo, Program, RungOut
from .vendor.logiclens_ladder import ALIASES, ParseError, Rung, iter_instructions, parse_program

MAX_COMMENT = 2000


@dataclass
class ElementDraft:
    mnemonic: str
    operands: List[str] = field(default_factory=list)
    bbox: Optional[List[float]] = None
    confidence: Optional[float] = None  # 0-100


@dataclass
class RungDraft:
    text: str
    number: Optional[int] = None
    comment: Optional[str] = None
    confidence: Optional[float] = None  # 0-100
    bbox: Optional[List[float]] = None
    elements: List[ElementDraft] = field(default_factory=list)


def canonical_mnemonic(word: str) -> str:
    upper = word.strip().upper()
    return ALIASES.get(upper, upper)


def parse_single_rung(text: str) -> Tuple[Optional[Rung], List[ParseError]]:
    """Exactly one valid rung, or the parser errors."""
    res = parse_program(text)
    if res.errors:
        return None, res.errors
    if len(res.rungs) != 1:
        return None, [ParseError("E_SYNTAX", f"expected exactly one rung, got {len(res.rungs)}", 0, 0)]
    return res.rungs[0], []


def _clip_confidence(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(min(100.0, max(0.0, float(value))), 1)


def finalize_rungs(drafts: Sequence[RungDraft], warnings: List[str]) -> List[RungOut]:
    out: List[RungOut] = []
    renumbered = False
    for position, draft in enumerate(drafts):
        rung, errors = parse_single_rung(draft.text)
        label = draft.number if draft.number is not None else position
        if rung is None:
            first = errors[0]
            warnings.append(f"Rung {label} dropped: {first.code} {first.message}"[:500])
            continue
        number = label
        if out and number <= out[-1].number:
            number = out[-1].number + 1
            renumbered = True
        elements = []
        for k, ins in enumerate(iter_instructions(rung.body)):
            draft_el = draft.elements[k] if k < len(draft.elements) else None
            matches = draft_el is not None and canonical_mnemonic(draft_el.mnemonic) == ins.mnemonic
            elements.append(Element(
                index=k, mnemonic=ins.mnemonic, operands=[o.raw for o in ins.operands],
                bbox=draft_el.bbox if matches else None,
                confidence=_clip_confidence(draft_el.confidence) if matches else None,
            ))
        comment = draft.comment[:MAX_COMMENT] if draft.comment else None
        out.append(RungOut(number=number, comment=comment, text=rung.text,
                           confidence=_clip_confidence(draft.confidence), bbox=draft.bbox, elements=elements))
    if renumbered:
        warnings.append("Rung numbers were not increasing and were renumbered.")
    return out


# ---------------------------------------------------------------------------- platform guess
_PLATFORM_PATTERNS = [
    ("rockwell_logix", re.compile(r"^Local:\d+:[IOC]\.", re.I)),
    ("rockwell_slc", re.compile(r"^(?:[OISBTCRNFLA]|ST|MG|PD)\d{0,3}:\d+(?:[./]\d+)?(?:\.[A-Z]+)?$")),
    ("generic_iec", re.compile(r"^%[IQM][XBWDL]\d+(?:\.\d+)*$", re.I)),
    ("siemens_tia", re.compile(r"^%?[IQM][BWD]?\d+(?:\.[0-7])?$", re.I)),
    ("mitsubishi", re.compile(r"^[XY][0-9A-F]{1,4}$")),
    ("omron", re.compile(r"^(?:CIO|W|H|D)?\d+\.\d{2}$", re.I)),
]


def guess_platform(rungs: Iterable[Rung]) -> Tuple[str, Optional[float]]:
    """Best-effort platform from the addressing style of tag operands; ('unknown', None) if unclear."""
    votes: Counter = Counter()
    total = 0
    for rung in rungs:
        for ins in iter_instructions(rung.body):
            for op in ins.operands:
                if op.type != "tag":
                    continue
                total += 1
                for platform, pattern in _PLATFORM_PATTERNS:
                    if pattern.match(op.raw):
                        votes[platform] += 1
                        break
    if not votes:
        return "unknown", None
    platform, count = votes.most_common(1)[0]
    share = count / max(total, 1)
    return platform, round(min(95.0, 40.0 + 55.0 * share), 1)


# ---------------------------------------------------------------------------- text endpoint
def program_from_text(text: str, platform: Optional[str]) -> Program:
    res = parse_program(text)
    if res.errors:
        raise ApiError(422, "E_LADDER_SYNTAX", f"The ladder text has {len(res.errors)} syntax error(s).",
                       details=[e.to_dict() for e in res.errors])
    if not res.rungs:
        raise ApiError(422, "E_LADDER_SYNTAX", "The ladder text contains no rungs.",
                       details=[{"code": "E_EMPTY_RUNG", "message": "program has no rungs", "line": 0, "col": 0}])
    rungs = []
    for rung in res.rungs:
        rungs.append(RungOut(
            number=rung.number, comment=rung.comment[:MAX_COMMENT] if rung.comment else None, text=rung.text,
            elements=[Element(index=k, mnemonic=i.mnemonic, operands=[o.raw for o in i.operands])
                      for k, i in enumerate(iter_instructions(rung.body))],
        ))
    if platform:
        chosen, confidence = platform, 100.0
    else:
        chosen, confidence = guess_platform(res.rungs)
    return Program(source="text", platform=chosen, platform_confidence=confidence, rungs=rungs, warnings=[],
                   engine=EngineInfo(name="text", version=__version__))
