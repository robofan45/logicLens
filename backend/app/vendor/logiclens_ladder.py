"""LogicLens Ladder Text (LLT) parser - Python reference implementation.

Mirrors web/src/engine/parse.ts. The grammar, limits and error codes are defined in
contract/README.md and pinned by contract/ladder_cases.json, which both parsers must pass.

The parser never raises on bad input: it returns every valid rung plus a list of errors.
No dependencies beyond the standard library, so the backend and the ML tooling can vendor it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

__all__ = [
    "LIMITS", "ALIASES", "SPEC", "Operand", "Instr", "Branch", "Seq", "Rung", "ParseError",
    "ParseResult", "parse_program", "parse_rung_text", "print_program", "print_rung",
    "iter_instructions", "timer_preset_ms", "classify_operand", "time_literal_ms",
]

LIMITS = {
    "program_chars": 200_000,
    "rungs": 2_000,
    "rung_chars": 4_000,
    "instructions": 256,
    "depth": 16,
    "operands": 8,
    "operand_chars": 120,
}

ALIASES = {
    "NO": "XIC", "NC": "XIO", "COIL": "OTE", "OUT": "OTE",
    "SET": "OTL", "S": "OTL", "RESET": "OTU", "R": "OTU",
}

# canonical mnemonic -> (min operands, max operands, role)
SPEC: Dict[str, Tuple[int, int, str]] = {
    "XIC": (1, 1, "in"), "XIO": (1, 1, "in"), "ONS": (1, 1, "in"), "P": (1, 1, "in"), "N": (1, 1, "in"),
    "EQU": (2, 2, "in"), "NEQ": (2, 2, "in"), "GRT": (2, 2, "in"), "GEQ": (2, 2, "in"),
    "LES": (2, 2, "in"), "LEQ": (2, 2, "in"), "LIM": (3, 3, "in"), "AFI": (0, 0, "in"), "LBL": (1, 1, "in"),
    "OTE": (1, 1, "out"), "OTL": (1, 1, "out"), "OTU": (1, 1, "out"), "NCOIL": (1, 1, "out"),
    "OSR": (2, 2, "out"), "OSF": (2, 2, "out"),
    "TON": (2, 4, "out"), "TOF": (2, 4, "out"), "RTO": (2, 4, "out"), "TP": (2, 3, "out"),
    "CTU": (2, 3, "out"), "CTD": (2, 3, "out"), "CTUD": (2, 3, "out"), "RES": (1, 1, "out"),
    "ADD": (3, 3, "out"), "SUB": (3, 3, "out"), "MUL": (3, 3, "out"), "DIV": (3, 3, "out"),
    "AND": (3, 3, "out"), "OR": (3, 3, "out"), "XOR": (3, 3, "out"),
    "MOV": (2, 2, "out"), "NOT": (2, 2, "out"),
    "JMP": (1, 1, "out"), "JSR": (1, 8, "out"), "MCR": (0, 0, "out"), "END": (0, 0, "out"), "NOP": (0, 0, "out"),
}

_LABEL_RE = re.compile(r"^\s*(?:(?:rung|network|n)\s*)?(\d+)\s*[:.)]\s*", re.IGNORECASE)
_BARE_N_RE = re.compile(r"^\s*N\s*:\s*", re.IGNORECASE)
_NUM_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_RADIX_RE = re.compile(r"^(2|8|16)#([0-9A-Fa-f_]+)$")
_RADIX_PREFIX_RE = re.compile(r"^\d+#")
_TIME_RE = re.compile(r"^(?:T|TIME)#(-?)([0-9a-zA-Z_.]+)$", re.IGNORECASE | re.ASCII)
_TIME_BODY_RE = re.compile(r"^(?:\d+(?:\.\d+)?(?:ms|d|h|m|s))+$", re.IGNORECASE | re.ASCII)
_TIME_PART_RE = re.compile(r"(\d+(?:\.\d+)?)(ms|d|h|m|s)", re.IGNORECASE | re.ASCII)
_TAG_RE = re.compile(r'^(?:"[^"\x00-\x1f]{1,118}"|[A-Za-z0-9_%#][A-Za-z0-9_:./\[\]%#]*)$')
_UNIT_MS = {"d": 86_400_000, "h": 3_600_000, "m": 60_000, "s": 1_000, "ms": 1}


@dataclass
class Operand:
    raw: str
    type: str  # "tag" | "number" | "time" | "unknown"
    value: Optional[float] = None

    def to_dict(self) -> dict:
        d = {"raw": self.raw, "type": self.type}
        if self.value is not None:
            d["value"] = self.value
        return d


@dataclass
class Instr:
    mnemonic: str
    operands: List[Operand]
    index: int
    col: int
    kind: str = "instr"
    id: str = ""

    @property
    def role(self) -> str:
        return SPEC[self.mnemonic][2]

    def to_dict(self) -> dict:
        return {"kind": "instr", "id": self.id, "mnemonic": self.mnemonic, "index": self.index,
                "col": self.col, "operands": [o.to_dict() for o in self.operands]}


@dataclass
class Branch:
    legs: List["Seq"]
    kind: str = "branch"

    def to_dict(self) -> dict:
        return {"kind": "branch", "legs": [leg.to_dict() for leg in self.legs]}


@dataclass
class Seq:
    items: List[Union[Instr, Branch]] = field(default_factory=list)
    kind: str = "seq"

    def to_dict(self) -> dict:
        return {"kind": "seq", "items": [i.to_dict() for i in self.items]}


@dataclass
class Rung:
    number: int
    comment: Optional[str]
    body: Seq
    line: int
    text: str = ""

    def to_dict(self) -> dict:
        return {"number": self.number, "comment": self.comment, "line": self.line,
                "text": self.text, "body": self.body.to_dict()}


@dataclass
class ParseError:
    code: str
    message: str
    line: int
    col: int

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "line": self.line, "col": self.col}


@dataclass
class ParseResult:
    rungs: List[Rung]
    errors: List[ParseError]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"ok": self.ok, "rungs": [r.to_dict() for r in self.rungs],
                "errors": [e.to_dict() for e in self.errors]}


class _RungError(Exception):
    def __init__(self, code: str, message: str, offset: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.offset = offset


def time_literal_ms(raw: str) -> Optional[float]:
    """Milliseconds for an IEC time literal such as T#1m30s, or None if it is not one."""
    m = _TIME_RE.match(raw)
    if not m:
        return None
    body = m.group(2).replace("_", "")
    if not body or not _TIME_BODY_RE.match(body):
        return None
    total = sum(float(n) * _UNIT_MS[u.lower()] for n, u in _TIME_PART_RE.findall(body))
    return -total if m.group(1) == "-" else total


def classify_operand(raw: str) -> Optional[Operand]:
    """Type an operand; None means the text is not a valid operand."""
    if raw == "?":
        return Operand(raw, "unknown")
    if _NUM_RE.match(raw):
        return Operand(raw, "number", float(raw))
    rm = _RADIX_RE.match(raw)
    if rm is None and _RADIX_PREFIX_RE.match(raw):
        return None  # looks like 16#.. / 2#.. but is not a valid radix literal
    if rm:
        digits = rm.group(2).replace("_", "")
        try:
            return Operand(raw, "number", float(int(digits, int(rm.group(1)))))
        except ValueError:
            return None
    if raw[:2].upper() == "T#" or raw[:5].upper() == "TIME#":
        ms = time_literal_ms(raw)
        return Operand(raw, "time", ms) if ms is not None else None
    if _TAG_RE.match(raw):
        return Operand(raw, "tag")
    return None


class _RungParser:
    """Recursive-descent parser for one rung body (no label, no ';')."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.count = 0

    def peek(self) -> Optional[str]:
        return self.s[self.i] if self.i < len(self.s) else None

    def skip_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def parse(self) -> Seq:
        seq = self.seq(0, False)
        self.skip_ws()
        if self.i < len(self.s):  # pragma: no cover - seq() consumes or raises
            raise _RungError("E_SYNTAX", f"unexpected '{self.s[self.i]}'", self.i)
        if self.count == 0:
            raise _RungError("E_EMPTY_RUNG", "rung has no instructions", 0)
        return seq

    def seq(self, depth: int, in_branch: bool) -> Seq:
        items: List[Union[Instr, Branch]] = []
        while True:
            self.skip_ws()
            c = self.peek()
            if c is None:
                if in_branch:
                    raise _RungError("E_UNBALANCED", "'[' is never closed", self.i)
                return Seq(items)
            if c == "[":
                if depth + 1 > LIMITS["depth"]:
                    raise _RungError("E_LIMIT", f"branches nested deeper than {LIMITS['depth']}", self.i)
                start = self.i
                self.i += 1
                legs = [self.seq(depth + 1, True)]
                while self.peek() == ",":
                    self.i += 1
                    legs.append(self.seq(depth + 1, True))
                if self.peek() != "]":
                    raise _RungError("E_UNBALANCED", "'[' is never closed", start)
                self.i += 1
                items.append(Branch(legs))
            elif c in ",]":
                if in_branch:
                    return Seq(items)
                if c == "]":
                    raise _RungError("E_UNBALANCED", "']' without a matching '['", self.i)
                raise _RungError("E_SYNTAX", "',' outside a branch", self.i)
            elif c == ")":
                raise _RungError("E_UNBALANCED", "')' without a matching '('", self.i)
            elif c.isalpha() or c == "_":
                items.append(self.instr())
            else:
                raise _RungError("E_SYNTAX", f"unexpected '{c}'", self.i)

    def instr(self) -> Instr:
        start = self.i
        while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] == "_"):
            self.i += 1
        word = self.s[start:self.i]
        self.skip_ws()
        if self.peek() != "(":
            raise _RungError("E_SYNTAX", f"expected '(' after {word}", self.i)
        upper = word.upper()
        mnemonic = ALIASES.get(upper, upper)
        if mnemonic not in SPEC:
            raise _RungError("E_UNKNOWN_MNEMONIC", f"unknown instruction '{word}'", start)
        operands = self.operands()
        if len(operands) > LIMITS["operands"]:
            raise _RungError("E_LIMIT", f"more than {LIMITS['operands']} operands", start)
        lo, hi, _ = SPEC[mnemonic]
        if not lo <= len(operands) <= hi:
            want = str(lo) if lo == hi else f"{lo}-{hi}"
            raise _RungError("E_ARITY", f"{mnemonic} takes {want} operands, got {len(operands)}", start)
        self.count += 1
        if self.count > LIMITS["instructions"]:
            raise _RungError("E_LIMIT", f"more than {LIMITS['instructions']} instructions", start)
        return Instr(mnemonic, operands, self.count - 1, start)

    def operands(self) -> List[Operand]:
        open_at = self.i
        self.i += 1  # consume '('
        parts: List[Tuple[str, int]] = []
        depth_p = 0
        depth_b = 0
        cur_start = self.i
        while True:
            c = self.peek()
            if c is None:
                raise _RungError("E_UNBALANCED", "'(' is never closed", open_at)
            if c == "(":
                depth_p += 1
            elif c == ")":
                if depth_p == 0:
                    parts.append((self.s[cur_start:self.i], cur_start))
                    self.i += 1
                    break
                depth_p -= 1
            elif c == "[":
                depth_b += 1
            elif c == "]":
                depth_b = max(0, depth_b - 1)
            elif c == "," and depth_p == 0 and depth_b == 0:
                parts.append((self.s[cur_start:self.i], cur_start))
                cur_start = self.i + 1
            self.i += 1
        if len(parts) == 1 and parts[0][0].strip() == "":
            return []
        out: List[Operand] = []
        for raw, at in parts:
            text = raw.strip()
            if not text:
                raise _RungError("E_EMPTY_OPERAND", "empty operand", at)
            if len(text) > LIMITS["operand_chars"]:
                raise _RungError("E_LIMIT", f"operand longer than {LIMITS['operand_chars']} characters", at)
            op = classify_operand(text)
            if op is None:
                raise _RungError("E_SYNTAX", f"invalid operand '{text[:40]}'", at)
            out.append(op)
        return out


def _split_line(line: str) -> Tuple[str, Optional[str]]:
    """Split a line into code and inline comment ('//' outside parentheses)."""
    depth = 0
    i = 0
    while i < len(line):
        c = line[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif c == "/" and depth == 0 and line[i:i + 2] == "//":
            return line[:i], line[i + 2:].strip()
        i += 1
    return line, None


def _segments(code: str, offset: int) -> List[Tuple[str, int]]:
    """Split code on ';' outside parentheses -> [(segment, start offset in line)]."""
    out = []
    depth = 0
    start = offset
    for i in range(offset, len(code)):
        c = code[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif c == ";" and depth == 0:
            out.append((code[start:i], start))
            start = i + 1
    out.append((code[start:], start))
    return out


def parse_rung_text(text: str, number: int = 0, comment: Optional[str] = None, line: int = 1,
                    col_offset: int = 0) -> Tuple[Optional[Rung], Optional[ParseError]]:
    """Parse one rung body (label already removed, no trailing ';')."""
    if len(text) > LIMITS["rung_chars"]:
        return None, ParseError("E_LIMIT", f"rung longer than {LIMITS['rung_chars']} characters", line, col_offset + 1)
    p = _RungParser(text)
    try:
        body = p.parse()
    except _RungError as e:
        return None, ParseError(e.code, e.message, line, col_offset + e.offset + 1)
    rung = Rung(number=number, comment=comment, body=body, line=line)
    rung.text = print_rung(rung)
    return rung, None


def parse_program(text: str) -> ParseResult:
    """Parse a whole LLT program. Never raises."""
    if not isinstance(text, str):
        return ParseResult([], [ParseError("E_SYNTAX", "program must be text", 0, 0)])
    if len(text) > LIMITS["program_chars"]:
        return ParseResult([], [ParseError("E_LIMIT", f"program longer than {LIMITS['program_chars']} characters", 0, 0)])
    rungs: List[Rung] = []
    errors: List[ParseError] = []
    pending: List[str] = []
    next_number = 0
    total = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            note = stripped[1:].strip()
            if note:
                pending.append(note)
            continue
        code, inline = _split_line(line)
        if not code.strip():
            if inline:
                pending.append(inline)
            continue
        label_num: Optional[int] = None
        offset = 0
        m = _LABEL_RE.match(code)
        if m:
            label_num = int(m.group(1))
            offset = m.end()
        else:
            mb = _BARE_N_RE.match(code)
            if mb:
                offset = mb.end()
        segs = [(s, at) for s, at in _segments(code, offset) if s.strip()]
        if not segs:
            if label_num is not None:
                errors.append(ParseError("E_EMPTY_RUNG", "label without a rung", line_no, 1))
                next_number = label_num + 1
            continue
        for k, (seg, at) in enumerate(segs):
            total += 1
            if total > LIMITS["rungs"]:
                errors.append(ParseError("E_LIMIT", f"more than {LIMITS['rungs']} rungs", line_no, 0))
                return _finish(rungs, errors)
            number = label_num if (k == 0 and label_num is not None) else next_number
            next_number = number + 1
            parts = pending if k == 0 else []
            if k == 0:
                pending = []
            if k == len(segs) - 1 and inline:
                parts = parts + [inline]
            comment = "\n".join(parts) if parts else None
            lead = len(seg) - len(seg.lstrip())
            rung, err = parse_rung_text(seg.strip(), number, comment, line_no, at + lead)
            if err:
                errors.append(err)
            else:
                rungs.append(rung)
    return _finish(rungs, errors)


def _finish(rungs: List[Rung], errors: List[ParseError]) -> ParseResult:
    for idx, rung in enumerate(rungs):
        for ins in iter_instructions(rung.body):
            ins.id = f"r{idx}i{ins.index}"
    return ParseResult(rungs, errors)


def iter_instructions(seq: Seq):
    """Instructions of a sequence in text order (depth-first, left to right)."""
    for item in seq.items:
        if isinstance(item, Instr):
            yield item
        else:
            for leg in item.legs:
                yield from iter_instructions(leg)


def _print_seq(seq: Seq) -> str:
    out = []
    for item in seq.items:
        if isinstance(item, Instr):
            out.append(f"{item.mnemonic}({','.join(o.raw for o in item.operands)})")
        else:
            out.append("[" + ",".join(_print_seq(leg) for leg in item.legs) + "]")
    return "".join(out)


def print_rung(rung: Rung) -> str:
    return _print_seq(rung.body) + ";"


def print_program(rungs: List[Rung], comments: bool = True) -> str:
    lines: List[str] = []
    for r in rungs:
        if comments and r.comment:
            lines.extend(f"// {c}" for c in r.comment.split("\n"))
        lines.append(print_rung(r))
    return "\n".join(lines)


def timer_preset_ms(ins: Instr) -> Optional[float]:
    """Preset in ms for TON/TOF/RTO/TP, None if it is a tag or unknown."""
    if ins.mnemonic not in ("TON", "TOF", "RTO", "TP"):
        return None
    ops = ins.operands
    if len(ops) == 4:  # SLC: timer, base (s), preset, accum
        base, pre = ops[1], ops[2]
        if base.type == "number" and pre.type == "number":
            return round(base.value * pre.value * 1000, 6)
        return None
    pre = ops[1]
    if pre.type == "time":
        return pre.value
    if pre.type == "number":
        return pre.value
    return None
