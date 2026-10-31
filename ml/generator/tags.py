"""Tag (operand) styles per PLC platform.

* ``rockwell_slc``   SLC 500 / MicroLogix data-table addresses: I:1/0, O:2/3, B3:0/1, T4:0, C5:0,
                     N7:0, F8:1, S:1/15; labels Q2:n, subroutine files U:n. RSLogix 500 prints bit
                     addresses split: file part above the symbol (``I:1``), bit number below (``0``).
* ``rockwell_logix`` Studio 5000 tag names: Start_PB, Motor_Run, Local:1:I.Data.0, Fill_Timer.DN.
* ``siemens_tia``    %I0.0, %Q0.0, %M10.0, %MW20, %IW64, quoted symbols ("Start_PB"), #locals.
* ``generic_iec``    IEC 61131-3 style identifiers: START_PB, T_FILL, C_PARTS.

Every operand produced here is accepted by the contract parser (``classify_operand``) and is at
most ``MAX_TAG_CHARS`` long, so the text printed above a contact stays inside the window the
backend OCR reads (about 5 symbol widths).
"""
from __future__ import annotations

import random
import re
from typing import Dict, List, Optional, Tuple

from .contract import llt

PLATFORMS = ("rockwell_slc", "rockwell_logix", "siemens_tia", "generic_iec")
MAX_TAG_CHARS = 16

_DEVICES = ["Motor", "Pump", "Fan", "Valve", "Conv", "Mixer", "Heater", "Comp", "Agitator", "Feeder",
            "Gate", "Door", "Horn", "Lamp", "Tank", "Silo", "Press", "Blower", "Damper", "Cyl", "Clamp",
            "Filler", "Capper", "Sorter", "Hoist", "Drum", "Dryer", "Chiller", "Boiler", "Kiln", "Crusher",
            "Screw", "Elev", "Diverter", "Stacker", "Wrapper", "Oven", "Dosing", "Heat", "Cool"]
_INPUT_FN = ["Start", "Stop", "Run_FB", "Fault", "Ready", "Auto", "Manual", "Reset", "EStop", "Open_LS",
             "Closed_LS", "High_LS", "Low_LS", "Level_Hi", "Level_Lo", "Press_Hi", "Temp_Hi", "Flow_OK",
             "Jog", "Fwd", "Rev", "Home_LS", "Prox", "Photo_Eye", "Door_SW", "Guard_OK", "OL", "Ack",
             "Sel_Auto", "Sel_Hand", "Part_Det", "Full", "Empty", "Up_LS", "Down_LS"]
_INPUT_SUFFIX = {"Start": "_PB", "Stop": "_PB", "Reset": "_PB", "Jog": "_PB", "Ack": "_PB", "EStop": "_OK"}
_OUTPUT_FN = ["Run", "On", "Open", "Close", "Fwd", "Rev", "Up", "Down", "Lamp", "Horn", "Alarm", "SOL",
              "Enable", "Start_Cmd", "Fast", "Slow", "Heat", "Fill", "Drain", "Beacon"]
_INTERNAL = ["Auto_Mode", "Man_Mode", "Seq_Step", "Cycle_On", "Cycle_Done", "Fault_Latch", "Run_Req",
             "Permissive", "Interlock_OK", "First_Scan", "Batch_Done", "Alarm_Act", "Pulse", "Flag",
             "Ready_Bit", "Step_Done", "Hold", "Purge_OK", "Warmup", "Mem_Bit"]
_WORDS = ["Level", "Speed_SP", "Temp_PV", "Press_PV", "Flow_PV", "Count", "Batch_Qty", "Recipe", "Setpoint",
          "Total", "Position", "Weight", "Step_No", "State", "Mode_Word", "Cycle_Time", "Rate", "Pct_Open",
          "Delta", "Offset", "Scaled", "Raw_Val", "Out_Val", "Index", "Status"]
_TIMER_FN = ["Fill", "Delay", "Run", "Purge", "Mix", "Drain", "Warmup", "Start", "Alarm", "Settle", "Dwell",
             "Cool", "Heat", "Debounce", "Pulse", "Cycle", "Ramp", "Wait"]
_COUNTER_FN = ["Parts", "Batch", "Cycles", "Rejects", "Boxes", "Bottles", "Strokes", "Faults", "Pieces", "Bags"]
_LABEL_FN = ["Skip", "Bypass", "End_Seq", "Retry", "Next", "Loop", "Done", "Manual", "Fault"]
_ROUTINE_FN = ["Fill", "Drain", "Alarms", "Motors", "Valves", "Seq", "Comms", "Scaling", "Recipe", "HMI",
               "Safety", "Diag", "Init", "Pid"]
DESCRIPTION_WORDS = ["START", "STOP", "PUSH", "BUTTON", "MOTOR", "PUMP", "VALVE", "RUN", "FAULT", "LIMIT",
                     "SWITCH", "TANK", "LEVEL", "HIGH", "LOW", "CONVEYOR", "LIGHT", "ALARM", "SEAL", "IN",
                     "AUX", "OVERLOAD", "TIMER", "DONE", "COUNT", "RESET", "AUTO", "MANUAL", "MODE", "FILL",
                     "DRAIN", "OPEN", "CLOSED", "SENSOR", "PHOTO", "EYE", "E-STOP", "OK", "READY", "HORN"]

_TIME_LITERALS = ["T#100ms", "T#250ms", "T#500ms", "T#1s", "T#2s", "T#3s", "T#5s", "T#10s", "T#15s", "T#30s",
                  "T#45s", "T#1m", "T#2m", "T#1m30s", "T#5m", "T#1s500ms", "T#20s", "T#8s"]
_INT_CONSTS = ["0", "1", "2", "3", "4", "5", "8", "10", "12", "15", "20", "25", "50", "60", "75", "80", "90",
               "100", "120", "150", "200", "250", "255", "500", "750", "1000", "1500", "2000", "4095", "32767",
               "-1", "-10", "16384"]
_REAL_CONSTS = ["0.5", "1.5", "2.5", "10.0", "12.5", "37.5", "45.0", "99.9", "100.0", "0.25", "3.14"]


def _title(word: str) -> str:
    return word


class TagSpace:
    """Generates platform-styled operands for one program. Deterministic for a given rng."""

    def __init__(self, platform: str, rng: random.Random):
        if platform not in PLATFORMS:
            raise ValueError(f"unknown platform {platform!r}")
        self.platform = platform
        self.rng = rng
        self._used: Dict[str, set] = {}
        self._n: Dict[str, int] = {}
        self.slc_bit_file = rng.choice(["B3", "B3", "B3", "B"])
        self.slc_in_slot = rng.choice([1, 1, 2])
        self.slc_out_slot = rng.choice([2, 2, 3, 0])
        self.tia_quote_rate = rng.uniform(0.0, 0.8)
        self.logix_module_rate = rng.uniform(0.0, 0.35)
        self.device_pool = rng.sample(_DEVICES, 8)

    # ------------------------------------------------------------------ helpers
    def _fresh(self, kind: str, make) -> str:
        used = self._used.setdefault(kind, set())
        for _ in range(60):
            tag = make()
            if len(tag) <= MAX_TAG_CHARS and tag.lower() not in used:
                used.add(tag.lower())
                op = llt.classify_operand(tag)
                assert op is not None and op.type == "tag", tag  # nosec B101 - internal invariant
                return tag
        # random pool exhausted: walk a numbered sequence until an unused tag turns up (always unique)
        while True:
            n = self._n[kind] = self._n.get(kind, 0) + 1
            tag = self._fallback(kind, n)
            if tag.lower() not in used:
                used.add(tag.lower())
                return tag

    def _fallback(self, kind: str, n: int) -> str:
        p = self.platform
        if p == "rockwell_slc":
            return {"din": f"I:{4 + n // 16}/{n % 16}", "dout": f"O:{5 + n // 16}/{n % 16}", "timer": f"T4:{20 + n}",
                    "counter": f"C5:{20 + n}", "word": f"N7:{60 + n}", "label": f"Q2:{10 + n}",
                    "routine": f"U:{16 + n}"}.get(kind, f"B3:{8 + n // 16}/{n % 16}")
        if p == "siemens_tia":
            return {"din": f"%I{8 + n // 8}.{n % 8}", "dout": f"%Q{8 + n // 8}.{n % 8}", "word": f"%MW{200 + 2 * n}",
                    "label": f"M{100 + n}", "routine": f"FC{200 + n}"}.get(kind, f"%M{100 + n // 8}.{n % 8}")
        base = {"din": "In", "dout": "Out", "timer": "Tmr", "counter": "Cnt", "word": "Val", "label": "Lbl",
                "routine": "Sub"}.get(kind, "Bit")
        tag = f"{base}_{n}"
        return tag.upper() if p == "generic_iec" else tag

    def _dev(self) -> str:
        d = self.rng.choice(self.device_pool)
        if self.rng.random() < 0.35:
            d += f"_{self.rng.randint(1, 4)}"
        return d

    def _case(self, name: str) -> str:
        return name.upper() if self.platform == "generic_iec" else name

    def _quote(self, name: str) -> str:
        return f'"{name}"'

    # ------------------------------------------------------------------ operands
    def din(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("din", lambda: f"I:{r.choice([self.slc_in_slot] * 3 + [1, 2, 3])}/{r.randint(0, 15)}")
        if p == "siemens_tia":
            if r.random() < self.tia_quote_rate:
                return self._fresh("din", lambda: self._quote(self._named_input()))
            return self._fresh("din", lambda: f"%I{r.randint(0, 3)}.{r.randint(0, 7)}")
        if p == "rockwell_logix" and r.random() < self.logix_module_rate:
            return self._fresh("din", lambda: f"Local:{r.randint(1, 4)}:I.Data.{r.randint(0, 15)}")
        return self._fresh("din", lambda: self._case(self._named_input()))

    def _named_input(self) -> str:
        fn = self.rng.choice(_INPUT_FN)
        if fn in _INPUT_SUFFIX and self.rng.random() < 0.5:
            return fn + _INPUT_SUFFIX[fn]
        if self.rng.random() < 0.3:
            return fn + _INPUT_SUFFIX.get(fn, "")
        return f"{self._dev()}_{fn}"

    def dout(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("dout", lambda: f"O:{r.choice([self.slc_out_slot] * 3 + [2, 3])}/{r.randint(0, 15)}")
        if p == "siemens_tia":
            if r.random() < self.tia_quote_rate:
                return self._fresh("dout", lambda: self._quote(f"{self._dev()}_{r.choice(_OUTPUT_FN)}"))
            return self._fresh("dout", lambda: f"%Q{r.randint(0, 3)}.{r.randint(0, 7)}")
        if p == "rockwell_logix" and r.random() < self.logix_module_rate:
            return self._fresh("dout", lambda: f"Local:{r.randint(2, 5)}:O.Data.{r.randint(0, 15)}")
        return self._fresh("dout", lambda: self._case(f"{self._dev()}_{r.choice(_OUTPUT_FN)}"))

    def bit(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            if r.random() < 0.04:
                return self._fresh("bit", lambda: r.choice(["S:1/15", "S:2/0", "S:1/14"]))
            if r.random() < 0.08:
                return self._fresh("bit", lambda: f"N7:{r.randint(0, 9)}/{r.randint(0, 15)}")
            return self._fresh("bit", lambda: f"{self.slc_bit_file}:{r.randint(0, 3)}/{r.randint(0, 15)}")
        if p == "siemens_tia":
            x = r.random()
            if x < self.tia_quote_rate:
                return self._fresh("bit", lambda: self._quote(r.choice(_INTERNAL)))
            if x < self.tia_quote_rate + 0.1:
                return self._fresh("bit", lambda: "#" + r.choice(["tmpBit", "statRun", "statDone", "edgeMem",
                                                                    "tmpOk", "statStep", "statFault"]))
            return self._fresh("bit", lambda: f"%M{r.randint(0, 99)}.{r.randint(0, 7)}")
        if p == "rockwell_logix" and r.random() < 0.15:
            return self._fresh("bit", lambda: f"{r.choice(['Alarm_Bits', 'Flags', 'Seq'])}[{r.randint(0, 31)}]")
        return self._fresh("bit", lambda: self._case(r.choice(_INTERNAL) + (f"_{r.randint(1, 9)}" if r.random() < 0.5 else "")))

    def timer(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("timer", lambda: f"T4:{r.randint(0, 19)}")
        if p == "siemens_tia":
            if r.random() < 0.6:
                return self._fresh("timer", lambda: f"#T_{r.choice(_TIMER_FN)}")
            return self._fresh("timer", lambda: f"T_{r.choice(_TIMER_FN)}{r.randint(1, 9)}")
        if p == "generic_iec":
            return self._fresh("timer", lambda: f"T_{r.choice(_TIMER_FN).upper()}" + (str(r.randint(1, 9)) if r.random() < 0.4 else ""))
        return self._fresh("timer", lambda: r.choice([f"{r.choice(_TIMER_FN)}_Timer", f"TMR_{r.choice(_TIMER_FN)}",
                                                       f"Timer_{r.randint(1, 20)}"]))

    def counter(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("counter", lambda: f"C5:{r.randint(0, 9)}")
        if p == "siemens_tia":
            return self._fresh("counter", lambda: r.choice([f"#C_{r.choice(_COUNTER_FN)}",
                                                             f"C_{r.choice(_COUNTER_FN)}{r.randint(1, 9)}"]))
        if p == "generic_iec":
            return self._fresh("counter", lambda: f"C_{r.choice(_COUNTER_FN).upper()}")
        return self._fresh("counter", lambda: r.choice([f"{r.choice(_COUNTER_FN)}_Count", f"CTR_{r.choice(_COUNTER_FN)}"]))

    def member(self, struct: str, which: str) -> str:
        """A timer/counter sub-element: which in DN, TT, EN, CU, ACC, PRE (mapped per platform)."""
        p = self.platform
        if p == "rockwell_slc":
            sep = "." if which in ("ACC", "PRE") else "/"
            return f"{struct}{sep}{which}"
        if p == "rockwell_logix":
            return f"{struct}.{which}"
        iec = {"DN": "Q", "TT": "Q", "EN": "Q", "CU": "Q", "ACC": "ET" if struct.upper().startswith(("T_", "#T_")) else "CV",
               "PRE": "PT" if struct.upper().startswith(("T_", "#T_")) else "PV"}[which]
        return f"{struct}.{iec}"

    def word(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            if r.random() < 0.15:
                return self._fresh("word", lambda: f"F8:{r.randint(0, 9)}")
            return self._fresh("word", lambda: f"N7:{r.randint(0, 49)}")
        if p == "siemens_tia":
            x = r.random()
            if x < self.tia_quote_rate * 0.8:
                return self._fresh("word", lambda: self._quote(r.choice(_WORDS)))
            if x < 0.75:
                return self._fresh("word", lambda: f"%MW{2 * r.randint(5, 60)}")
            return self._fresh("word", lambda: r.choice([f"%IW{64 + 2 * r.randint(0, 7)}", f"%DB{r.randint(1, 9)}.DBW{2 * r.randint(0, 20)}",
                                                          f"#tmp{r.choice(['Int', 'Val', 'Real', 'Cnt'])}"]))
        if p == "rockwell_logix" and r.random() < 0.15:
            return self._fresh("word", lambda: f"{r.choice(['Recipe', 'Data', 'Buffer'])}[{r.randint(0, 31)}]")
        return self._fresh("word", lambda: self._case(r.choice(_WORDS) + (f"_{r.randint(1, 9)}" if r.random() < 0.3 else "")))

    def label(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("label", lambda: f"Q2:{r.randint(0, 9)}")
        if p == "siemens_tia":
            return self._fresh("label", lambda: r.choice([f"M{r.randint(1, 99):03d}", f"SKP{r.randint(1, 9)}",
                                                           f"L{r.randint(10, 99)}"]))
        return self._fresh("label", lambda: self._case(f"{r.choice(_LABEL_FN)}_{r.randint(1, 9)}"))

    def routine(self) -> str:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            return self._fresh("routine", lambda: f"U:{r.randint(3, 15)}")
        if p == "siemens_tia":
            return self._fresh("routine", lambda: r.choice([f"FC{r.randint(1, 120)}", f"FB{r.randint(1, 60)}"]))
        if p == "generic_iec":
            return self._fresh("routine", lambda: f"{r.choice(_ROUTINE_FN).upper()}_SUB")
        return self._fresh("routine", lambda: f"{r.choice(_ROUTINE_FN)}_Routine" if r.random() < 0.6 else f"R{r.randint(10, 99)}_{r.choice(_ROUTINE_FN)}")

    # ------------------------------------------------------------------ constants
    def int_const(self) -> str:
        if self.platform in ("siemens_tia", "generic_iec") and self.rng.random() < 0.06:
            return self.rng.choice(["16#FF", "16#0F", "16#00FF", "2#1010"])
        return self.rng.choice(_INT_CONSTS)

    def real_const(self) -> str:
        return self.rng.choice(_REAL_CONSTS)

    def value(self) -> str:
        """A compare/math source: a word tag most of the time, else a constant."""
        if self.rng.random() < 0.55:
            return self.word()
        return self.real_const() if self.rng.random() < 0.15 else self.int_const()

    def timer_operands(self, mnemonic: str, timer: str) -> List[str]:
        r, p = self.rng, self.platform
        if p == "rockwell_slc":
            base = r.choice(["0.01", "0.01", "1.0", "0.001"])
            preset = r.choice(["5", "10", "20", "30", "50", "100", "150", "250", "300", "500", "1000", "3000"])
            return [timer, base, preset, r.choice(["0", "0", "0", "12", "37"])]
        if p == "rockwell_logix":
            preset = r.choice(["500", "1000", "1500", "2000", "3000", "5000", "10000", "15000", "30000", "60000"])
            return [timer, preset, r.choice(["0", "0", "0", "250", "1200"])]
        ops = [timer, r.choice(_TIME_LITERALS)]
        return ops

    def counter_operands(self, mnemonic: str, counter: str) -> List[str]:
        r = self.rng
        preset = r.choice(["3", "5", "10", "12", "20", "24", "50", "100", "144", "500", "1000"])
        if self.platform in ("rockwell_slc", "rockwell_logix"):
            return [counter, preset, r.choice(["0", "0", "0", "3", "17"])]
        return [counter, preset]


# ---------------------------------------------------------------------- display helpers
_SLC_SPLIT = re.compile(r"^((?:[A-Z]|ST|MG|PD|BT)\d{0,3}:\d+)/(\d{1,2})$")


def split_slc_address(tag: str) -> Optional[Tuple[str, str]]:
    """RSLogix 500 display split: 'I:1/3' -> ('I:1', '3'); sub-elements ('T4:0/DN') stay whole."""
    m = _SLC_SPLIT.match(tag)
    return (m.group(1), m.group(2)) if m else None


def description_for(rng: random.Random, words: int = 0) -> str:
    n = words or rng.choice([1, 2, 2, 3])
    return " ".join(rng.choice(DESCRIPTION_WORDS) for _ in range(n))


def all_kinds() -> List[str]:
    return ["din", "dout", "bit", "timer", "counter", "word", "label", "routine"]
