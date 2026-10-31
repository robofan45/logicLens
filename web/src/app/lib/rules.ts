// Human-readable catalogue of the engine's checks (Docs page). Typed as Record<RuleId, ...> so
// the build fails if the engine gains a rule that is not documented here.

import type { RuleId } from "../../engine";

export interface RuleDoc {
  title: string;
  basis: "rule" | "heuristic";
  what: string;
}

export const RULE_DOCS: Record<RuleId, RuleDoc> = {
  DUPLICATE_OUTPUT: { title: "Double coil", basis: "rule", what: "The same bit is written by OTE/NCOIL in more than one place; the last write in the scan wins and earlier logic is silently overridden." },
  MIXED_OUTPUT_TYPES: { title: "OTE mixed with latch/unlatch", basis: "rule", what: "A bit driven by both OTE and OTL/OTU; the OTE rewrites it every scan." },
  LATCH_WITHOUT_UNLATCH: { title: "Latch without unlatch", basis: "rule", what: "OTL with no OTU (or other write) for the same bit: it can never turn off." },
  UNLATCH_WITHOUT_LATCH: { title: "Unlatch without latch", basis: "rule", what: "OTU of a bit that nothing ever sets." },
  TIMER_INSTANCE_REUSED: { title: "Timer/counter instance reused", basis: "rule", what: "The same timer or counter driven by more than one instruction (CTU+CTD on one counter is allowed)." },
  TIMER_PRESET_INVALID: { title: "Timer preset invalid", basis: "rule", what: "Preset zero or negative, above the DINT range, above 32767 on SLC, or set from a tag at run time." },
  COUNTER_PRESET_INVALID: { title: "Counter preset invalid", basis: "rule", what: "Counter preset zero or negative." },
  COUNTER_NO_RESET: { title: "Counter never reset", basis: "rule", what: "CTU/CTD/CTUD with no RES and no write to its accumulator." },
  RTO_NO_RESET: { title: "Retentive timer never reset", basis: "rule", what: "RTO keeps its accumulated time until RES; without one it stays done forever." },
  DEAD_RUNG: { title: "Dead rung", basis: "rule", what: "An output whose condition can never be true (contradiction, impossible compare range, AFI)." },
  CONTRADICTORY_CONTACTS: { title: "Contradictory contacts", basis: "rule", what: "XIC(A) and XIO(A) in series on one path: that path never passes power." },
  ALWAYS_TRUE: { title: "Always-true condition", basis: "rule", what: "A condition that is a tautology, so the output never turns off." },
  BRANCH_BYPASSED: { title: "Branch bypassed by an empty leg", basis: "rule", what: "An empty branch leg is a plain wire that short-circuits the contacts beside it." },
  UNCONDITIONAL_OUTPUT: { title: "Unconditional output", basis: "rule", what: "An output with no condition in front of it." },
  MISSING_SEAL_IN: { title: "Missing seal-in", basis: "heuristic", what: "A momentary start button drives an OTE with no holding contact or latch (judged from tag names)." },
  MISSING_INTERLOCK: { title: "Missing interlock", basis: "heuristic", what: "An actuator-looking output (motor, pump, valve, heater...) with no stop or permissive in its condition." },
  ESTOP_IN_STANDARD_LOGIC: { title: "E-stop in standard logic", basis: "heuristic", what: "An emergency stop appears in standard PLC logic. It must be a hard-wired or safety-rated function (ISO 13850, IEC 60204-1, ISO 13849-1 / IEC 62061); the PLC should only monitor it." },
  STOP_EXAMINED_WITH_XIO: { title: "Stop examined with XIO", basis: "heuristic", what: "Fail-safe practice wires stops NC and examines them with XIC, so a broken wire stops the machine. XIO means NO wiring." },
  REDUNDANT_CONTACT: { title: "Redundant contact", basis: "rule", what: "The same contact twice on one path, or identical parallel legs." },
  SCAN_ORDER_DELAY: { title: "Scan-order delay", basis: "rule", what: "An internal bit is read before the rung that writes it, so it lags one scan." },
  UNUSED_INTERNAL: { title: "Unused internal bit", basis: "rule", what: "An internal bit that is written but never read." },
  UNDEFINED_TIMER_REFERENCE: { title: "Undefined timer/counter", basis: "rule", what: "A .DN/.ACC member is read but no instruction in this program drives that timer or counter." },
  JUMP_TARGET_MISSING: { title: "Jump target missing", basis: "rule", what: "JMP to a label that does not exist." },
  LABEL_DUPLICATE: { title: "Duplicate label", basis: "rule", what: "The same LBL appears more than once." },
  LBL_NOT_FIRST: { title: "LBL not first on its rung", basis: "rule", what: "A label must be the first instruction of its rung." },
  BACKWARD_JUMP: { title: "Backward jump", basis: "rule", what: "Jumping to an earlier rung loops inside one scan and risks the watchdog." },
  MCR_UNBALANCED: { title: "Unbalanced MCR zone", basis: "rule", what: "A conditional MCR with no closing unconditional MCR." },
  ONE_SHOT_STORAGE_REUSED: { title: "One-shot storage bit reused", basis: "rule", what: "Two ONS/OSR/OSF instructions share a storage bit and break each other's edge detection." },
  DIVIDE_BY_ZERO: { title: "Division by zero", basis: "rule", what: "DIV with a literal 0 divisor." },
  UNKNOWN_OPERANDS: { title: "Unread operands", basis: "rule", what: "Operands shown as ? (not recognised from the image): check them against the picture." },
  MISSING_COMMENT: { title: "Rungs without comments", basis: "rule", what: "One summary finding listing uncommented rungs." },
  NAMING_INCONSISTENCY: { title: "Inconsistent naming", basis: "heuristic", what: "One summary finding when address-style and symbolic names, or several case styles, are mixed." },
};

export const RULE_COUNT = Object.keys(RULE_DOCS).length;
