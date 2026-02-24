import logging
import time
from typing import Any, Dict, List, Optional

from models.schemas import LadderProgram, SimulatorState

logger = logging.getLogger(__name__)

SCAN_INTERVAL_MS = 10.0  # simulated scan cycle time in milliseconds


class LadderSimulator:
    """
    Full PLC scan-cycle simulator for LadderProgram objects.

    Supported instructions:
      Contacts : NO, NC, OSR, OSF
      Coils    : OUTPUT, SET, RESET, NEGATED
      Timers   : TON, TOF, RTO, TP
      Counters : CTU, CTD, CTUD
      Compare  : EQU, NEQ, GRT, LES, GEQ, LEQ
      Math     : ADD, SUB, MUL, DIV, MOV
    """

    def __init__(self, program: LadderProgram) -> None:
        self._program = program
        self._inputs: Dict[str, bool] = {}
        self._outputs: Dict[str, bool] = {}
        self._memory: Dict[str, bool] = {}  # internal memory bits
        self._data: Dict[str, float] = {}   # numeric data registers
        self._timers: Dict[str, Dict[str, Any]] = {}
        self._counters: Dict[str, Dict[str, Any]] = {}
        self._prev_coil: Dict[str, bool] = {}  # previous scan values for edge detection
        self._scan_count: int = 0
        self._wall_last_scan: float = time.monotonic()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def toggle_input(self, address: str, value: Optional[bool] = None) -> None:
        if value is None:
            self._inputs[address] = not self._inputs.get(address, False)
        else:
            self._inputs[address] = value

    def reset(self) -> None:
        self._inputs.clear()
        self._outputs.clear()
        self._memory.clear()
        self._data.clear()
        self._timers.clear()
        self._counters.clear()
        self._prev_coil.clear()
        self._scan_count = 0

    def get_state(self) -> SimulatorState:
        return SimulatorState(
            inputs=dict(self._inputs),
            outputs=dict(self._outputs),
            timers={k: dict(v) for k, v in self._timers.items()},
            counters={k: dict(v) for k, v in self._counters.items()},
            scan_count=self._scan_count,
        )

    # ------------------------------------------------------------------
    # Scan cycle
    # ------------------------------------------------------------------

    def scan(self) -> Dict[str, Any]:
        """Execute one complete scan cycle. Returns rung results and updated state."""
        now = time.monotonic()
        elapsed_ms = (now - self._wall_last_scan) * 1000.0
        self._wall_last_scan = now

        rung_results: List[Dict[str, Any]] = []

        for rung in self._program.rungs:
            rung_power = self._evaluate_rung(rung, elapsed_ms)
            rung_results.append(
                {
                    "rung_number": rung.rung_number,
                    "is_powered": rung_power,
                }
            )

        self._scan_count += 1
        return {
            "rung_results": rung_results,
            "state": self.get_state().model_dump(),
        }

    # ------------------------------------------------------------------
    # Rung evaluation
    # ------------------------------------------------------------------

    def _evaluate_rung(self, rung: Any, elapsed_ms: float) -> bool:
        """
        Evaluate a LadderRung and write outputs. Returns True if outputs were energised.
        """
        # Evaluate main series path
        power = self._eval_series(rung.series_elements)

        # Evaluate any parallel branches (each branch ORed together, then ANDed with series)
        if rung.parallel_branches:
            branch_power = any(
                self._eval_series(branch.elements) for branch in rung.parallel_branches
            )
            power = power and branch_power

        # Write outputs
        for out_elem in rung.outputs:
            self._write_output(out_elem, power, elapsed_ms)

        return power

    def _eval_series(self, elements: List[dict]) -> bool:
        """AND all contacts / logic blocks in series."""
        power = True
        for elem in elements:
            if not power:
                break
            power = power and self._eval_element(elem)
        return power

    def _eval_element(self, elem: dict) -> bool:
        etype = elem.get("element_type", "Unknown")
        addr = elem.get("address", "")

        if etype == "NO_Contact":
            return self._read_bit(addr)
        if etype == "NC_Contact":
            return not self._read_bit(addr)
        if etype == "OSR_OneShotRising":
            return self._one_shot_rising(addr)
        if etype == "OSF_OneShotFalling":
            return self._one_shot_falling(addr)

        # Compare instructions – require props
        props = elem.get("properties", {})
        if etype in ("EQU_Equal", "NEQ_NotEqual", "GRT_GreaterThan",
                     "LES_LessThan", "GEQ_GreaterEqual", "LEQ_LessEqual"):
            return self._eval_compare(etype, addr, props)

        # Wire / unknown elements pass power through
        return True

    # ------------------------------------------------------------------
    # Output writing
    # ------------------------------------------------------------------

    def _write_output(self, elem: dict, power: bool, elapsed_ms: float) -> None:
        etype = elem.get("element_type", "Unknown")
        addr = elem.get("address", "")
        props = elem.get("properties", {})

        if etype == "Output_Coil":
            self._write_bit(addr, power)
        elif etype == "Negated_Coil":
            self._write_bit(addr, not power)
        elif etype == "Set_Coil":
            if power:
                self._write_bit(addr, True)
        elif etype == "Reset_Coil":
            if power:
                self._write_bit(addr, False)
        elif etype in ("TON_Timer", "RTO_Timer", "TP_Timer"):
            self._eval_ton(addr, power, props, elapsed_ms)
        elif etype == "TOF_Timer":
            self._eval_tof(addr, power, props, elapsed_ms)
        elif etype == "CTU_Counter":
            self._eval_ctu(addr, power, props)
        elif etype == "CTD_Counter":
            self._eval_ctd(addr, power, props)
        elif etype == "CTUD_Counter":
            self._eval_ctud(addr, power, props)
        elif etype == "RES_Reset":
            if power:
                self._reset_timer_counter(addr)
        elif etype in ("ADD_Addition", "SUB_Subtraction",
                       "MUL_Multiplication", "DIV_Division", "MOV_Move"):
            if power:
                self._eval_math(etype, addr, props)

    # ------------------------------------------------------------------
    # Bit helpers
    # ------------------------------------------------------------------

    def _read_bit(self, addr: str) -> bool:
        if addr in self._inputs:
            return self._inputs[addr]
        if addr in self._outputs:
            return self._outputs[addr]
        return self._memory.get(addr, False)

    def _write_bit(self, addr: str, value: bool) -> None:
        if addr.upper().startswith("I") or addr.upper().startswith("%I"):
            self._inputs[addr] = value
        elif addr.upper().startswith("Q") or addr.upper().startswith("%Q"):
            self._outputs[addr] = value
        else:
            self._memory[addr] = value

    # ------------------------------------------------------------------
    # Edge detection
    # ------------------------------------------------------------------

    def _one_shot_rising(self, addr: str) -> bool:
        current = self._read_bit(addr)
        prev = self._prev_coil.get(f"osr_{addr}", False)
        self._prev_coil[f"osr_{addr}"] = current
        return current and not prev

    def _one_shot_falling(self, addr: str) -> bool:
        current = self._read_bit(addr)
        prev = self._prev_coil.get(f"osf_{addr}", True)
        self._prev_coil[f"osf_{addr}"] = current
        return not current and prev

    # ------------------------------------------------------------------
    # Timers
    # ------------------------------------------------------------------

    def _get_timer(self, addr: str, preset_ms: float) -> Dict[str, Any]:
        if addr not in self._timers:
            self._timers[addr] = {
                "preset": preset_ms,
                "accumulated": 0.0,
                "done": False,
                "timing": False,
            }
        return self._timers[addr]

    def _eval_ton(self, addr: str, enable: bool, props: dict, elapsed_ms: float) -> None:
        preset = float(props.get("preset", 1000))
        t = self._get_timer(addr, preset)
        if enable:
            t["timing"] = True
            t["accumulated"] = min(t["accumulated"] + elapsed_ms, preset)
            t["done"] = t["accumulated"] >= preset
        else:
            t["accumulated"] = 0.0
            t["done"] = False
            t["timing"] = False
        self._write_bit(f"{addr}.DN", t["done"])
        self._write_bit(f"{addr}.TT", t["timing"] and not t["done"])

    def _eval_tof(self, addr: str, enable: bool, props: dict, elapsed_ms: float) -> None:
        preset = float(props.get("preset", 1000))
        t = self._get_timer(addr, preset)
        if enable:
            t["accumulated"] = 0.0
            t["done"] = True
        else:
            if t["done"]:
                t["timing"] = True
                t["accumulated"] = min(t["accumulated"] + elapsed_ms, preset)
                if t["accumulated"] >= preset:
                    t["done"] = False
                    t["timing"] = False
        self._write_bit(f"{addr}.DN", t["done"])

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    def _get_counter(self, addr: str, preset: int) -> Dict[str, Any]:
        if addr not in self._counters:
            self._counters[addr] = {"preset": preset, "accumulated": 0, "done": False}
        return self._counters[addr]

    def _eval_ctu(self, addr: str, enable: bool, props: dict) -> None:
        preset = int(props.get("preset", 10))
        c = self._get_counter(addr, preset)
        prev = self._prev_coil.get(f"ctu_{addr}", False)
        if enable and not prev:
            c["accumulated"] += 1
            c["done"] = c["accumulated"] >= c["preset"]
        self._prev_coil[f"ctu_{addr}"] = enable
        self._write_bit(f"{addr}.DN", c["done"])

    def _eval_ctd(self, addr: str, enable: bool, props: dict) -> None:
        preset = int(props.get("preset", 10))
        c = self._get_counter(addr, preset)
        prev = self._prev_coil.get(f"ctd_{addr}", False)
        if enable and not prev:
            c["accumulated"] = max(0, c["accumulated"] - 1)
            c["done"] = c["accumulated"] == 0
        self._prev_coil[f"ctd_{addr}"] = enable
        self._write_bit(f"{addr}.DN", c["done"])

    def _eval_ctud(self, addr: str, enable: bool, props: dict) -> None:
        up_enable = enable and bool(props.get("count_up", True))
        down_enable = enable and bool(props.get("count_down", False))
        self._eval_ctu(addr, up_enable, props)
        if down_enable:
            c = self._counters.get(addr, {})
            c["accumulated"] = max(0, c.get("accumulated", 0) - 1)

    def _reset_timer_counter(self, addr: str) -> None:
        if addr in self._timers:
            self._timers[addr]["accumulated"] = 0.0
            self._timers[addr]["done"] = False
            self._timers[addr]["timing"] = False
        if addr in self._counters:
            self._counters[addr]["accumulated"] = 0
            self._counters[addr]["done"] = False

    # ------------------------------------------------------------------
    # Compare & Math
    # ------------------------------------------------------------------

    def _eval_compare(self, etype: str, addr: str, props: dict) -> bool:
        source_a = float(self._data.get(addr, props.get("source_a", 0)))
        source_b = float(props.get("source_b", 0))
        if etype == "EQU_Equal":
            return source_a == source_b
        if etype == "NEQ_NotEqual":
            return source_a != source_b
        if etype == "GRT_GreaterThan":
            return source_a > source_b
        if etype == "LES_LessThan":
            return source_a < source_b
        if etype == "GEQ_GreaterEqual":
            return source_a >= source_b
        if etype == "LEQ_LessEqual":
            return source_a <= source_b
        return False

    def _eval_math(self, etype: str, dest: str, props: dict) -> None:
        src_a = float(self._data.get(props.get("source_a", ""), props.get("value_a", 0)))
        src_b = float(self._data.get(props.get("source_b", ""), props.get("value_b", 0)))
        if etype == "ADD_Addition":
            self._data[dest] = src_a + src_b
        elif etype == "SUB_Subtraction":
            self._data[dest] = src_a - src_b
        elif etype == "MUL_Multiplication":
            self._data[dest] = src_a * src_b
        elif etype == "DIV_Division":
            self._data[dest] = src_a / src_b if src_b != 0 else 0.0
        elif etype == "MOV_Move":
            self._data[dest] = src_a
