"""Random but realistic LLT programs.

Rungs come from templates that mirror what real programs contain: motor seal-in circuits with stop
and overload, interlock chains, timers whose done bit is used later, counters with RES, compares,
math and moves, one-shots, IEC edge contacts, latch/unlatch pairs, parallel output branches,
nested branches (depth <= 2), JMP/LBL, JSR, MCR zones and (as the last rung) END.

Layout conventions the templates respect (contract section 6, backend assembler):
* outputs only at the end of a rung; several outputs form a parallel output branch;
* inputs only before the outputs; a leg of an output branch may start with one condition;
* an empty (wire) leg is only ever the last leg of a top-level input branch;
* branch depth <= 2; only mnemonics with a detector class are used.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from .contract import ID_BY_MNEMONIC, llt
from .tags import TagSpace

# ----------------------------------------------------------------------------- program model


@dataclass
class Ins:
    m: str
    ops: List[str] = field(default_factory=list)

    def text(self) -> str:
        return f"{self.m}({','.join(self.ops)})"

    @property
    def role(self) -> str:
        return llt.SPEC[self.m][2]


@dataclass
class Br:
    legs: List[List["Item"]]

    def text(self) -> str:
        return "[" + ",".join(seq_text(leg) for leg in self.legs) + "]"


Item = Union[Ins, Br]


def seq_text(items: Sequence[Item]) -> str:
    return "".join(i.text() for i in items)


@dataclass
class SampledRung:
    body: List[Item]
    template: str
    comment: Optional[str] = None

    def text(self) -> str:
        return seq_text(self.body) + ";"


@dataclass
class SampledProgram:
    platform: str
    rungs: List[SampledRung]

    def text(self, comments: bool = True) -> str:
        lines: List[str] = []
        for r in self.rungs:
            if comments and r.comment:
                lines.extend(f"// {c}" for c in r.comment.split("\n"))
            lines.append(r.text())
        return "\n".join(lines)


def walk(items: Sequence[Item]):
    """Instructions in text order."""
    for it in items:
        if isinstance(it, Ins):
            yield it
        else:
            for leg in it.legs:
                yield from walk(leg)


def depth(items: Sequence[Item]) -> int:
    best = 0
    for it in items:
        if isinstance(it, Br):
            best = max(best, 1 + max(depth(leg) for leg in it.legs))
    return best


# ----------------------------------------------------------------------------- platforms

_ROCKWELL = {"XIC", "XIO", "OTE", "OTL", "OTU", "TON", "TOF", "RTO", "CTU", "CTD", "RES", "EQU", "NEQ", "GRT",
             "LES", "GEQ", "LEQ", "ADD", "SUB", "MUL", "DIV", "MOV", "AND", "OR", "XOR", "NOT", "OSR", "OSF",
             "JMP", "LBL", "JSR", "MCR", "END"}
_IEC = {"XIC", "XIO", "P", "N", "OTE", "NCOIL", "OTL", "OTU", "TON", "TOF", "RTO", "TP", "CTU", "CTD", "CTUD",
        "RES", "EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ", "ADD", "SUB", "MUL", "DIV", "MOV", "AND", "OR", "XOR",
        "NOT", "JMP", "LBL", "JSR", "MCR"}
SUPPORTED: Dict[str, frozenset] = {
    "rockwell_slc": frozenset(_ROCKWELL),
    "rockwell_logix": frozenset(_ROCKWELL),
    "siemens_tia": frozenset(_IEC),
    "generic_iec": frozenset(_IEC - {"MCR"}),
}
for _p, _ms in SUPPORTED.items():  # every emitted mnemonic must have a detector class
    assert _ms <= set(ID_BY_MNEMONIC), _ms - set(ID_BY_MNEMONIC)  # nosec B101 - import-time invariant

COMPARES = ("EQU", "NEQ", "GRT", "LES", "GEQ", "LEQ")
MATH3 = ("ADD", "SUB", "MUL", "DIV")
LOGIC3 = ("AND", "OR", "XOR")
TIMERS_ROCKWELL = ("TON", "TOF", "RTO")
TIMERS_IEC = ("TON", "TOF", "TP", "RTO")
COUNTERS_ROCKWELL = ("CTU", "CTD")
COUNTERS_IEC = ("CTU", "CTD", "CTUD")

# Base template weights. Tuned so every class reaches >= ~150 instances per 2000 images (see the
# class-coverage test and the dataset report).
TEMPLATE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "rockwell_slc": {"seal_in": 8, "interlock": 8, "or_logic": 6, "timer": 9, "timer_done": 5, "counter": 7,
                     "reset": 4, "compare": 21, "math": 15, "logic_word": 12, "oneshot": 13, "latch": 5,
                     "parallel_out": 7, "nested": 5, "jump": 8, "subroutine": 5, "mcr": 5},
    "rockwell_logix": {"seal_in": 8, "interlock": 8, "or_logic": 6, "timer": 9, "timer_done": 5, "counter": 7,
                       "reset": 4, "compare": 21, "math": 15, "logic_word": 12, "oneshot": 13, "latch": 5,
                       "parallel_out": 7, "nested": 5, "jump": 8, "subroutine": 5, "mcr": 5},
    "siemens_tia": {"seal_in": 6, "interlock": 7, "or_logic": 5, "timer": 11, "timer_done": 5, "counter": 9,
                    "reset": 4, "compare": 19, "math": 13, "logic_word": 11, "edge": 9, "latch": 5,
                    "parallel_out": 7, "nested": 5, "jump": 8, "subroutine": 5, "mcr": 3, "ncoil": 6},
    "generic_iec": {"seal_in": 6, "interlock": 7, "or_logic": 5, "timer": 11, "timer_done": 5, "counter": 9,
                    "reset": 4, "compare": 19, "math": 13, "logic_word": 11, "edge": 9, "latch": 5,
                    "parallel_out": 7, "nested": 5, "jump": 8, "subroutine": 5, "ncoil": 6},
}

_COMMENTS = {
    "seal_in": ["{d} start/stop with seal-in", "{d} motor control", "Start {d}, stop or overload drops out",
                "{d} run circuit"],
    "interlock": ["{d} permissives", "{d} interlock chain", "Enable {d} when all permissives OK", "Output {d}"],
    "or_logic": ["{d} from local or remote", "Any {d} condition", "{d} request"],
    "timer": ["{d} delay timer", "Time the {d} cycle", "{d} timer", "Delay before {d}"],
    "timer_done": ["{d} after time elapsed", "Timer done -> {d}", "{d} delay complete"],
    "counter": ["Count {d} parts", "{d} batch counter", "Counter for {d}"],
    "reset": ["Reset {d} counter", "Reset {d} timer", "Clear accumulators"],
    "compare": ["{d} level alarm", "{d} high/low check", "Compare {d} to setpoint", "{d} range check"],
    "math": ["Scale {d}", "{d} calculation", "Totalize {d}", "Move {d} setpoint"],
    "logic_word": ["Mask {d} status word", "{d} word logic", "Pack {d} bits"],
    "oneshot": ["{d} one-shot", "Edge detect {d}"],
    "edge": ["{d} rising edge", "Detect {d} edge", "{d} edge pulse"],
    "latch": ["Latch {d}", "Unlatch {d}", "{d} memory"],
    "parallel_out": ["{d} outputs", "Drive {d} and indicators", "{d} sequence step"],
    "nested": ["{d} logic", "{d} combined permissives", "{d} enable"],
    "jump": ["Skip {d} when bypassed", "{d} jump"],
    "subroutine": ["Call {d} routine", "{d} subroutine"],
    "mcr": ["{d} MCR zone", "Master control {d}"],
    "ncoil": ["{d} not running", "Inverted {d} status"],
}


class ProgramSampler:
    """Samples programs for one platform. All randomness comes from ``rng``."""

    def __init__(self, platform: str, rng: random.Random, comment_rate: float = 0.0):
        self.platform = platform
        self.rng = rng
        self.tags = TagSpace(platform, rng)
        self.ok = SUPPORTED[platform]
        self.comment_rate = comment_rate
        self.timers: List[Tuple[str, str]] = []      # (tag, mnemonic)
        self.counters: List[Tuple[str, str]] = []
        self.coils: List[str] = []                   # bits written by coils (usable as contacts)
        self.words: List[str] = []
        self.pending_labels: List[str] = []
        self.mcr_open = False
        self.iec = platform in ("siemens_tia", "generic_iec")

    # ------------------------------------------------------------------ public
    def sample(self, n_rungs: int) -> SampledProgram:
        weights = TEMPLATE_WEIGHTS[self.platform]
        names = sorted(weights)
        rungs: List[SampledRung] = []
        for _ in range(n_rungs):
            rungs.append(self.rung(self.rng.choices(names, [weights[n] for n in names])[0]))
        return SampledProgram(self.platform, rungs)

    def rung(self, template: str) -> SampledRung:
        body = getattr(self, f"_t_{template}")()
        comment = None
        if self.comment_rate and self.rng.random() < self.comment_rate:
            dev = self.rng.choice(self.tags.device_pool).replace("_", " ")
            comment = self.rng.choice(_COMMENTS.get(template, ["{d}"])).format(d=dev)
            if self.rng.random() < 0.15:
                comment += "\n" + self.rng.choice(["See P&ID sheet 4", "Do not bypass", "Modified 2024-03",
                                                   "Per spec 7.2", "HMI faceplate 12"])
        return SampledRung(body, template, comment)

    def end_rung(self) -> SampledRung:
        return SampledRung([Ins("END", [])], "end")

    # ------------------------------------------------------------------ building blocks
    def _contact(self, tag: Optional[str] = None, nc: Optional[bool] = None) -> Ins:
        r = self.rng
        if tag is None:
            x = r.random()
            if self.coils and x < 0.2:
                tag = r.choice(self.coils)
            elif x < 0.32:
                tag = self.tags.bit()
            else:
                tag = self.tags.din()
        if nc is None:
            nc = r.random() < 0.3
        if self.iec and r.random() < 0.08:
            return Ins(r.choice(["P", "N"]), [tag])
        return Ins("XIO" if nc else "XIC", [tag])

    def _conditions(self, lo: int, hi: int) -> List[Item]:
        return [self._contact() for _ in range(self.rng.randint(lo, hi))]

    def _coil_tag(self) -> str:
        tag = self.tags.dout() if self.rng.random() < 0.6 else self.tags.bit()
        self.coils.append(tag)
        return tag

    def _coil(self) -> Ins:
        r = self.rng
        x = r.random()
        if x < 0.62:
            return Ins("OTE", [self._coil_tag()])
        if x < 0.76:
            return Ins("OTL", [self._coil_tag()])
        if x < 0.88:
            return Ins("OTU", [r.choice(self.coils) if self.coils else self._coil_tag()])
        if "NCOIL" in self.ok:
            return Ins("NCOIL", [self._coil_tag()])
        return Ins("OTE", [self._coil_tag()])

    def _timer(self) -> Ins:
        m = self.rng.choice(TIMERS_IEC if self.iec else TIMERS_ROCKWELL)
        if self.iec and self.rng.random() < 0.3:
            m = "TP"
        t = self.tags.timer()
        self.timers.append((t, m))
        return Ins(m, self.tags.timer_operands(m, t))

    def _counter(self) -> Ins:
        m = self.rng.choice(COUNTERS_IEC if self.iec else COUNTERS_ROCKWELL)
        if self.iec and self.rng.random() < 0.4:
            m = "CTUD"
        c = self.tags.counter()
        self.counters.append((c, m))
        return Ins(m, self.tags.counter_operands(m, c))

    def _compare(self) -> Ins:
        m = self.rng.choice(COMPARES)
        a = self._word_source()
        b = self.tags.value() if self.rng.random() < 0.5 else self.tags.int_const()
        return Ins(m, [a, b])

    def _word_source(self) -> str:
        r = self.rng
        if self.timers and r.random() < 0.15:
            return self.tags.member(r.choice(self.timers)[0], "ACC")
        if self.counters and r.random() < 0.15:
            return self.tags.member(r.choice(self.counters)[0], "ACC")
        if self.words and r.random() < 0.35:
            return r.choice(self.words)
        w = self.tags.word()
        self.words.append(w)
        return w

    def _dest(self) -> str:
        if self.words and self.rng.random() < 0.3:
            return self.rng.choice(self.words)
        w = self.tags.word()
        self.words.append(w)
        return w

    def _math(self) -> Ins:
        r = self.rng
        x = r.random()
        if x < 0.4:
            src = self.tags.value() if r.random() < 0.6 else self.tags.int_const()
            return Ins("MOV", [src, self._dest()])
        m = r.choice(MATH3)
        return Ins(m, [self._word_source(), self.tags.value(), self._dest()])

    def _logic_word(self) -> Ins:
        r = self.rng
        if r.random() < 0.3:
            return Ins("NOT", [self._word_source(), self._dest()])
        m = r.choice(LOGIC3)
        mask = r.choice(["16#00FF", "16#FF00", "255", "15", "240", "4095"]) if self.iec else r.choice(
            ["255", "15", "240", "4095", "-256"])
        return Ins(m, [self._word_source(), mask if r.random() < 0.6 else self._word_source(), self._dest()])

    def _output_box(self) -> Ins:
        r = self.rng
        x = r.random()
        if x < 0.3:
            return self._timer()
        if x < 0.5:
            return self._counter()
        if x < 0.75:
            return self._math()
        if x < 0.85:
            return self._logic_word()
        return self._coil()

    def _any_output(self) -> Ins:
        return self._coil() if self.rng.random() < 0.6 else self._output_box()

    def _parallel_outputs(self, n: Optional[int] = None) -> Br:
        r = self.rng
        n = n or r.choice([2, 2, 2, 3, 3, 4])
        legs = []
        for k in range(n):
            leg: List[Item] = []
            if k > 0 and r.random() < 0.18:
                leg.append(self._contact())
            leg.append(self._any_output())
            legs.append(leg)
        return Br(legs)

    def _outputs(self, single: Optional[Callable[[], Ins]] = None, p_parallel: float = 0.25) -> List[Item]:
        if self.rng.random() < p_parallel:
            return [self._parallel_outputs()]
        return [(single or self._any_output)()]

    def _or_branch(self, legs: Optional[int] = None, allow_empty: bool = True) -> Br:
        r = self.rng
        n = legs or r.choice([2, 2, 2, 3, 3, 4])
        out = [self._conditions(1, 2) for _ in range(n)]
        if allow_empty and r.random() < 0.03:
            out.append([])  # wire leg (always true) - last leg only
        return Br(out)

    def _maybe_mcr_end(self, body: List[Item]) -> List[Item]:
        return body

    # ------------------------------------------------------------------ templates
    def _t_seal_in(self) -> List[Item]:
        r = self.rng
        motor = self._coil_tag()
        start = self.tags.din()
        stop = self.tags.din()
        seal = [Ins("XIC", [motor])]
        legs: List[List[Item]] = [[Ins("XIC", [start])], seal]
        if r.random() < 0.25:
            legs.append([Ins("XIC", [self.tags.din()])])  # remote start
        body: List[Item] = []
        if r.random() < 0.3:
            body.append(Ins("XIC", [stop]))
            body.append(Br(legs))
        else:
            body.append(Br(legs))
            body.append(Ins(r.choice(["XIC", "XIO"]), [stop]))
        if r.random() < 0.75:
            body.append(Ins("XIO", [self.tags.din()]))  # overload
        if r.random() < 0.3:
            body.append(self._contact())
        if r.random() < 0.35:
            legs_out: List[List[Item]] = [[Ins("OTE", [motor])], [self._coil()]]
            if r.random() < 0.3:
                legs_out.append([self._output_box()])
            body.append(Br(legs_out))
        else:
            body.append(Ins("OTE", [motor]))
        return body

    def _t_interlock(self) -> List[Item]:
        return self._conditions(1, 5) + self._outputs(self._coil, p_parallel=0.15)

    def _t_or_logic(self) -> List[Item]:
        r = self.rng
        body: List[Item] = []
        if r.random() < 0.5:
            body += self._conditions(1, 2)
        body.append(self._or_branch())
        if r.random() < 0.5:
            body += self._conditions(1, 2)
        return body + self._outputs(p_parallel=0.2)

    def _t_timer(self) -> List[Item]:
        body = self._conditions(0, 3) if self.rng.random() < 0.9 else []
        if self.rng.random() < 0.2:
            return body + [Br([[self._timer()], [self._coil()]])]
        return body + [self._timer()]

    def _t_timer_done(self) -> List[Item]:
        r = self.rng
        if not self.timers:
            self.timers.append((self.tags.timer(), "TON"))
        t, m = r.choice(self.timers)
        which = r.choice(["DN", "DN", "DN", "TT", "EN"]) if not self.iec else "DN"
        body: List[Item] = [Ins("XIC" if r.random() < 0.85 else "XIO", [self.tags.member(t, which)])]
        body += self._conditions(0, 2)
        return body + self._outputs(self._coil, p_parallel=0.25)

    def _t_counter(self) -> List[Item]:
        r = self.rng
        body = self._conditions(1, 2)
        if r.random() < 0.25:
            c = self._counter()
            return body + [Br([[c], [self._coil()]])]
        return body + [self._counter()]

    def _t_reset(self) -> List[Item]:
        r = self.rng
        pool = self.timers + self.counters
        target = r.choice(pool)[0] if pool else (self.tags.counter() if r.random() < 0.5 else self.tags.timer())
        body = self._conditions(1, 2)
        if r.random() < 0.3 and len(pool) > 1:
            other = r.choice([p for p in pool if p[0] != target] or pool)[0]
            return body + [Br([[Ins("RES", [target])], [Ins("RES", [other])]])]
        return body + [Ins("RES", [target])]

    def _t_compare(self) -> List[Item]:
        r = self.rng
        body: List[Item] = []
        if r.random() < 0.35:
            body += self._conditions(1, 2)
        x = r.random()
        if x < 0.55:
            body.append(self._compare())
        elif x < 0.8:
            body += [self._compare(), self._compare()]
        else:
            body.append(Br([[self._compare()], [self._compare()]]))
        return body + self._outputs(p_parallel=0.2)

    def _t_math(self) -> List[Item]:
        r = self.rng
        body = self._conditions(0, 2)
        if r.random() < 0.3:
            return body + [Br([[self._math()], [self._math()]] + ([[self._math()]] if r.random() < 0.3 else []))]
        return body + [self._math()]

    def _t_logic_word(self) -> List[Item]:
        body = self._conditions(0, 2)
        if self.rng.random() < 0.25:
            return body + [Br([[self._logic_word()], [self._logic_word()]])]
        return body + [self._logic_word()]

    def _t_oneshot(self) -> List[Item]:
        r = self.rng
        body = self._conditions(1, 2)
        m = "OSR" if r.random() < 0.55 else "OSF"
        ins = Ins(m, [self.tags.bit(), self._coil_tag()])
        if r.random() < 0.2:
            return body + [Br([[ins], [self._coil()]])]
        return body + [ins]

    def _t_edge(self) -> List[Item]:
        r = self.rng
        body: List[Item] = [Ins(r.choice(["P", "P", "N"]), [self.tags.din() if r.random() < 0.7 else self.tags.bit()])]
        body += self._conditions(0, 2)
        if r.random() < 0.2:
            body.insert(0, Ins(r.choice(["P", "N"]), [self.tags.din()]))
        return body + self._outputs(p_parallel=0.2)

    def _t_latch(self) -> List[Item]:
        r = self.rng
        tag = r.choice(self.coils) if self.coils and r.random() < 0.4 else self._coil_tag()
        body = self._conditions(1, 3)
        m = "OTL" if r.random() < 0.55 else "OTU"
        if r.random() < 0.2:
            return body + [Br([[Ins(m, [tag])], [Ins("OTU" if m == "OTL" else "OTL", [self._coil_tag()])]])]
        return body + [Ins(m, [tag])]

    def _t_parallel_out(self) -> List[Item]:
        return self._conditions(1, 3) + [self._parallel_outputs()]

    def _t_nested(self) -> List[Item]:
        r = self.rng
        inner = Br([self._conditions(1, 2), self._conditions(1, 1)])
        shape = r.random()
        if shape < 0.45:      # nested branch in the first leg
            outer = Br([[inner] + (self._conditions(0, 1)), self._conditions(1, 2)])
        elif shape < 0.75:    # nested branch in the last leg
            outer = Br([self._conditions(1, 2), self._conditions(1, 1) + [inner]])
        else:                 # nested branch in a middle leg
            outer = Br([self._conditions(1, 1), self._conditions(0, 1) + [inner], self._conditions(1, 1)])
        body: List[Item] = self._conditions(0, 1) + [outer] + self._conditions(0, 1)
        return body + self._outputs(p_parallel=0.2)

    def _t_jump(self) -> List[Item]:
        r = self.rng
        if r.random() < 0.5:  # jump target; the matching JMP may sit outside the visible window
            lbl = self.pending_labels.pop(0) if self.pending_labels else self.tags.label()
            return [Ins("LBL", [lbl])] + self._conditions(0, 2) + self._outputs(self._coil, p_parallel=0.1)
        lbl = self.tags.label()
        self.pending_labels.append(lbl)
        return self._conditions(1, 2) + [Ins("JMP", [lbl])]

    def _t_subroutine(self) -> List[Item]:
        body = self._conditions(0, 2) if self.rng.random() < 0.7 else []
        return body + [Ins("JSR", [self.tags.routine()])]

    def _t_mcr(self) -> List[Item]:
        if self.mcr_open:
            self.mcr_open = False
            return [Ins("MCR", [])]
        self.mcr_open = True
        return self._conditions(1, 3) + [Ins("MCR", [])]

    def _t_ncoil(self) -> List[Item]:
        out = Ins("NCOIL", [self._coil_tag()])
        if self.rng.random() < 0.2:
            return self._conditions(1, 3) + [Br([[out], [self._coil()]])]
        return self._conditions(1, 3) + [out]


def sample_program(platform: str, rng: random.Random, n_rungs: int, comment_rate: float = 0.0) -> SampledProgram:
    return ProgramSampler(platform, rng, comment_rate).sample(n_rungs)
