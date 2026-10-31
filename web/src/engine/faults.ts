// Rule-based fault detection over a parsed program.
//
// Every finding says whether it comes from a deterministic rule (structure, satisfiability)
// or a naming heuristic, with a confidence. Standards are cited at document level only.

import { iterInstructions, printSeq, roleOf, timerPresetMs } from "./parse";
import { analyzeExpr } from "./sat";
import { physicalClass, splitMember, tagKey, tagWords, type Instance } from "./tags";
import type { Instr, Mnemonic, ParseError, Rung, Seq } from "./types";
import { buildXref, exprToString, isAtom, writeTargets, type Expr, type OutputCondition, type TagInfo, type Xref } from "./xref";

export type Severity = "critical" | "high" | "medium" | "low";

export const CHECKLIST_KEYS = [
  "RACE_CONDITION",
  "MISSING_INTERLOCK",
  "MISSING_SAFETY_INPUT",
  "COIL_CONFLICT",
  "LATCH_WITHOUT_UNLATCH",
  "BYPASSED_SAFETY",
  "DEAD_RUNG",
  "ALWAYS_TRUE",
  "MISSING_SEAL_IN",
  "TIMER_OVERFLOW",
  "COUNTER_NO_RESET",
  "WRONG_CONTACT_TYPE",
  "BROKEN_BRANCH",
  "MISSING_PERMISSIVE",
  "REDUNDANT_LOGIC",
  "SUBOPTIMAL_ORDER",
  "NAMING_INCONSISTENCY",
  "MISSING_COMMENT",
  "UNUSED_TAG",
] as const;
export type ChecklistKey = (typeof CHECKLIST_KEYS)[number];

export type RuleId =
  | "DUPLICATE_OUTPUT"
  | "MIXED_OUTPUT_TYPES"
  | "LATCH_WITHOUT_UNLATCH"
  | "UNLATCH_WITHOUT_LATCH"
  | "TIMER_INSTANCE_REUSED"
  | "TIMER_PRESET_INVALID"
  | "COUNTER_PRESET_INVALID"
  | "COUNTER_NO_RESET"
  | "RTO_NO_RESET"
  | "DEAD_RUNG"
  | "CONTRADICTORY_CONTACTS"
  | "ALWAYS_TRUE"
  | "BRANCH_BYPASSED"
  | "UNCONDITIONAL_OUTPUT"
  | "MISSING_SEAL_IN"
  | "MISSING_INTERLOCK"
  | "ESTOP_IN_STANDARD_LOGIC"
  | "STOP_EXAMINED_WITH_XIO"
  | "REDUNDANT_CONTACT"
  | "SCAN_ORDER_DELAY"
  | "UNUSED_INTERNAL"
  | "UNDEFINED_TIMER_REFERENCE"
  | "JUMP_TARGET_MISSING"
  | "LABEL_DUPLICATE"
  | "LBL_NOT_FIRST"
  | "BACKWARD_JUMP"
  | "MCR_UNBALANCED"
  | "ONE_SHOT_STORAGE_REUSED"
  | "DIVIDE_BY_ZERO"
  | "UNKNOWN_OPERANDS"
  | "MISSING_COMMENT"
  | "NAMING_INCONSISTENCY";

export interface Finding {
  id: string;
  rule: RuleId;
  /** Primary Playbook checklist item, null when the rule is outside the 19 items. */
  checklist: ChecklistKey | null;
  severity: Severity;
  title: string;
  description: string;
  recommendation: string;
  /** Rung numbers involved, ascending. */
  rungs: number[];
  instrIds: string[];
  /** Display names of the tags involved. */
  tags: string[];
  confidence: number;
  basis: "rule" | "heuristic";
  standard?: string;
}

export type ChecklistStatus = "FOUND" | "NOT_FOUND" | "NOT_APPLICABLE";

export interface ChecklistEntry {
  status: ChecklistStatus;
  reason?: string;
  findings: string[];
}

export type Grade = "Healthy" | "Minor issues" | "Needs attention" | "Critical";

export interface FaultReport {
  findings: Finding[];
  checklist: Record<ChecklistKey, ChecklistEntry>;
  riskScore: number;
  grade: Grade;
  counts: Record<Severity, number> & { total: number };
}

export interface FaultOptions {
  platform?: string;
  context?: string;
  /** Reuse a cross reference that was already built for these rungs. */
  xref?: Xref;
}

/** Every checklist item a rule's findings mark as FOUND. */
const RULE_CHECKLIST: Record<RuleId, ChecklistKey[]> = {
  DUPLICATE_OUTPUT: ["COIL_CONFLICT", "RACE_CONDITION"],
  MIXED_OUTPUT_TYPES: ["COIL_CONFLICT"],
  LATCH_WITHOUT_UNLATCH: ["LATCH_WITHOUT_UNLATCH"],
  UNLATCH_WITHOUT_LATCH: ["LATCH_WITHOUT_UNLATCH"],
  TIMER_INSTANCE_REUSED: ["RACE_CONDITION"],
  TIMER_PRESET_INVALID: ["TIMER_OVERFLOW"],
  COUNTER_PRESET_INVALID: ["TIMER_OVERFLOW"],
  COUNTER_NO_RESET: ["COUNTER_NO_RESET"],
  RTO_NO_RESET: ["COUNTER_NO_RESET"],
  DEAD_RUNG: ["DEAD_RUNG"],
  CONTRADICTORY_CONTACTS: ["DEAD_RUNG"],
  ALWAYS_TRUE: ["ALWAYS_TRUE"],
  BRANCH_BYPASSED: ["ALWAYS_TRUE"],
  UNCONDITIONAL_OUTPUT: ["ALWAYS_TRUE"],
  MISSING_SEAL_IN: ["MISSING_SEAL_IN"],
  MISSING_INTERLOCK: ["MISSING_INTERLOCK", "MISSING_PERMISSIVE"],
  ESTOP_IN_STANDARD_LOGIC: [],
  STOP_EXAMINED_WITH_XIO: ["WRONG_CONTACT_TYPE"],
  REDUNDANT_CONTACT: ["REDUNDANT_LOGIC"],
  SCAN_ORDER_DELAY: ["SUBOPTIMAL_ORDER"],
  UNUSED_INTERNAL: ["UNUSED_TAG"],
  UNDEFINED_TIMER_REFERENCE: [],
  JUMP_TARGET_MISSING: [],
  LABEL_DUPLICATE: [],
  LBL_NOT_FIRST: [],
  BACKWARD_JUMP: [],
  MCR_UNBALANCED: [],
  ONE_SHOT_STORAGE_REUSED: ["COIL_CONFLICT"],
  DIVIDE_BY_ZERO: [],
  UNKNOWN_OPERANDS: [],
  MISSING_COMMENT: ["MISSING_COMMENT"],
  NAMING_INCONSISTENCY: ["NAMING_INCONSISTENCY"],
};

const WEIGHT: Record<Severity, number> = { critical: 0.45, high: 0.25, medium: 0.1, low: 0.02 };
const RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** risk = round(100 * (1 - prod(1 - w))). */
export function riskOf(severities: Severity[]): { riskScore: number; grade: Grade } {
  const keep = severities.reduce((p, s) => p * (1 - WEIGHT[s]), 1);
  const riskScore = Math.round(100 * (1 - keep));
  const grade: Grade = riskScore < 20 ? "Healthy" : riskScore < 50 ? "Minor issues" : riskScore < 75 ? "Needs attention" : "Critical";
  return { riskScore, grade };
}

type Draft = Omit<Finding, "id" | "checklist"> & { checklist?: ChecklistKey | null };

const uniq = <T>(xs: T[]): T[] => [...new Set(xs)];
const sortNum = (xs: number[]) => uniq(xs).sort((a, b) => a - b);
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
const listRungs = (rs: number[]) => {
  const s = sortNum(rs);
  return s.length === 1 ? `rung ${s[0]}` : `rungs ${s.slice(0, -1).join(", ")} and ${s[s.length - 1]}`;
};

const COIL_WRITES: ReadonlySet<Mnemonic> = new Set<Mnemonic>(["OTE", "NCOIL"]);
const COMMAND_WORDS = new Set(["CMD", "HMI", "REQ", "REQUEST", "COMMAND", "SCADA"]);
const STRONG_MEMBERS = new Set(["DN", "TT", "ACC", "PRE", "CU", "CD", "OV", "UN"]);
const IEC_MEMBER_NAMES = new Set(["Q", "ET", "CV", "PV"]);
const NO_UNCONDITIONAL: ReadonlySet<Mnemonic> = new Set<Mnemonic>(["MCR", "END", "NOP", "JSR"]);

function instrRung(x: Xref, id: string): number {
  return x.instructions.get(id)!.rung;
}

/** Literal of a condition node: [tag key, polarity] for XIC / XIO reads. */
function literal(e: Expr): [string, boolean] | null {
  if (e.op === "var") return [e.key, true];
  if (e.op === "not" && e.arg.op === "var") return [e.arg.key, false];
  return null;
}

/** Walk conjunctions, reporting literals repeated (same polarity) or contradicted on one path. */
function scanLiterals(
  e: Expr,
  ctx: Map<string, boolean>,
  onDup: (key: string) => void,
  onConflict: (key: string) => void,
): void {
  const lit = literal(e);
  if (lit) {
    const seen = ctx.get(lit[0]);
    if (seen === lit[1]) onDup(lit[0]);
    else if (seen !== undefined) onConflict(lit[0]);
    return;
  }
  if (e.op === "and") {
    const local = new Map(ctx);
    for (const a of e.args) {
      const l = literal(a);
      if (!l) continue;
      const seen = local.get(l[0]);
      if (seen === l[1]) onDup(l[0]);
      else if (seen !== undefined) onConflict(l[0]);
      else local.set(l[0], l[1]);
    }
    for (const a of e.args) if (!literal(a)) scanLiterals(a, local, onDup, onConflict);
  } else if (e.op === "or") {
    for (const a of e.args) scanLiterals(a, ctx, onDup, onConflict);
  }
}

function hasPositiveVar(e: Expr, key: string): boolean {
  switch (e.op) {
    case "var":
      return e.key === key;
    case "and":
    case "or":
      return e.args.some((a) => hasPositiveVar(a, key));
    default:
      return false;
  }
}

function positiveVarTags(e: Expr, out: string[] = []): string[] {
  if (e.op === "var") out.push(e.key.slice(2));
  else if (e.op === "and" || e.op === "or") for (const a of e.args) positiveVarTags(a, out);
  return out;
}

function atomList(e: Expr, out: Expr[] = []): Expr[] {
  if (isAtom(e)) out.push(e);
  else if (e.op === "not") atomList(e.arg, out);
  else if (e.op === "and" || e.op === "or") for (const a of e.args) atomList(a, out);
  return out;
}

function identicalLegs(seq: Seq, out: string[]): void {
  for (const item of seq.items) {
    if (item.kind !== "branch") continue;
    const texts = item.legs.map(printSeq).filter((t) => t !== "");
    const seen = new Set<string>();
    for (const t of texts) {
      if (seen.has(t)) out.push(t);
      seen.add(t);
    }
    for (const leg of item.legs) identicalLegs(leg, out);
  }
}

export function analyzeFaults(rungs: Rung[], parseErrors: ParseError[] = [], opts: FaultOptions = {}): FaultReport {
  const x = opts.xref ?? buildXref(rungs, { platform: opts.platform });
  const drafts: Draft[] = [];
  const add = (d: Draft) => drafts.push(d);
  const tags = [...x.tags.values()];
  const tagOf = (key: string): TagInfo | undefined => x.tags.get(key);
  const allInstrs: { ins: Instr; rung: Rung; rungIndex: number }[] = [];
  rungs.forEach((rung, rungIndex) => {
    for (const ins of iterInstructions(rung.body)) allInstrs.push({ ins, rung, rungIndex });
  });

  // ---------------------------------------------------------------- coils and latches
  for (const t of tags) {
    const coil = t.writes.filter((w) => COIL_WRITES.has(w.mnemonic));
    const otl = t.writes.filter((w) => w.mnemonic === "OTL");
    const otu = t.writes.filter((w) => w.mnemonic === "OTU");
    const other = t.writes.filter((w) => !["OTL", "OTU"].includes(w.mnemonic));
    if (coil.length >= 2) {
      const physical = t.physical === "output" || t.hints.includes("actuator");
      const last = coil[coil.length - 1];
      add({
        rule: "DUPLICATE_OUTPUT",
        severity: physical ? "critical" : "high",
        title: `${t.display} is driven by ${coil.length} coils`,
        description: `${t.display} is written by ${coil.map((w) => `${w.mnemonic} in rung ${w.rung}`).join(", ")}. In one scan the coil in rung ${last.rung} wins, so the earlier coil logic is overwritten every scan and only shows up as a one-scan glitch.`,
        recommendation:
          "Drive the output from a single rung: OR the conditions together in parallel branches and delete the other coils, or use OTL/OTU with explicit priority.",
        rungs: sortNum(coil.map((w) => w.rung)),
        instrIds: coil.map((w) => w.instrId),
        tags: [t.display],
        confidence: 95,
        basis: "rule",
        standard: "IEC 61131-3",
      });
    }
    if (coil.length && (otl.length || otu.length)) {
      const refs = [...coil, ...otl, ...otu];
      add({
        rule: "MIXED_OUTPUT_TYPES",
        severity: "medium",
        title: `${t.display} mixes OTE with OTL/OTU`,
        description: `${t.display} is driven by a non-retentive coil and by latch/unlatch instructions (${listRungs(refs.map((r) => r.rung))}). The OTE rewrites the bit every scan, so the latch state does not survive and the behaviour depends on rung order.`,
        recommendation: "Use either one OTE rung or an OTL/OTU pair for this bit, not both.",
        rungs: sortNum(refs.map((r) => r.rung)),
        instrIds: refs.map((r) => r.instrId),
        tags: [t.display],
        confidence: 90,
        basis: "rule",
      });
    }
    const clears = otu.length + other.length;
    if (otl.length && clears === 0) {
      add({
        rule: "LATCH_WITHOUT_UNLATCH",
        severity: "high",
        title: `${t.display} is latched but never unlatched`,
        description: `${t.display} is set with OTL in ${listRungs(otl.map((r) => r.rung))} and nothing in this program clears it, so once set it stays set (also across power cycles, since OTL bits are retentive).`,
        recommendation: `Add an unlatch path, e.g. a reset/acknowledge rung ending in OTU(${t.display}), and make sure it is reachable after the cause clears.`,
        rungs: sortNum(otl.map((r) => r.rung)),
        instrIds: otl.map((r) => r.instrId),
        tags: [t.display],
        confidence: 90,
        basis: "rule",
      });
    }
    if (otu.length && otl.length === 0 && other.length === 0) {
      add({
        rule: "UNLATCH_WITHOUT_LATCH",
        severity: "low",
        title: `${t.display} is unlatched but never latched here`,
        description: `${t.display} is cleared with OTU in ${listRungs(otu.map((r) => r.rung))} but no instruction in this program sets it. It may be set by another routine or an HMI; otherwise the OTU has no effect.`,
        recommendation: "Confirm where the bit is set, or remove the unused unlatch.",
        rungs: sortNum(otu.map((r) => r.rung)),
        instrIds: otu.map((r) => r.instrId),
        tags: [t.display],
        confidence: 60,
        basis: "rule",
      });
    }
  }

  // ---------------------------------------------------------------- timers and counters
  for (const inst of x.instances.values()) {
    const legitUpDown = inst.instrIds.length === 2 && inst.mnemonics.length === 2 && inst.mnemonics.includes("CTU") && inst.mnemonics.includes("CTD");
    if (inst.instrIds.length >= 2 && !legitUpDown) {
      const rs = inst.instrIds.map((id) => instrRung(x, id));
      add({
        rule: "TIMER_INSTANCE_REUSED",
        severity: "high",
        title: `${inst.display} is driven by ${inst.instrIds.length} ${inst.kind} instructions`,
        description: `${inst.display} is used by ${inst.instrIds.map((id) => `${x.instructions.get(id)!.instr.mnemonic} in rung ${instrRung(x, id)}`).join(", ")}. Each instruction updates the same accumulator and done bit, so they fight every scan (in Structured Text this is the classic "function block called twice per scan" bug).`,
        recommendation: `Give every ${inst.kind} instruction its own instance, or merge the conditions into one rung; use RES to reset an instance instead of driving it from a second rung.`,
        rungs: sortNum(rs),
        instrIds: [...inst.instrIds],
        tags: [inst.display],
        confidence: 95,
        basis: "rule",
        standard: "IEC 61131-3",
      });
    }
    const accWritten = tags.some(
      (t) => t.memberOf === inst.key && splitMember(t.display)?.member === "ACC" && t.writes.length > 0,
    );
    const reset = inst.resets.length > 0 || accWritten;
    if (inst.kind === "counter" && !reset) {
      add({
        rule: "COUNTER_NO_RESET",
        severity: "medium",
        title: `${inst.display} is never reset`,
        description: `Nothing in this program resets ${inst.display} (no RES and no write to its accumulator). Once it reaches its preset it stays done and keeps counting until it overflows.`,
        recommendation: `Add a rung with RES(${inst.display}) on the condition that starts a new batch/cycle.`,
        rungs: sortNum(inst.instrIds.map((id) => instrRung(x, id))),
        instrIds: [...inst.instrIds],
        tags: [inst.display],
        confidence: 85,
        basis: "rule",
      });
    }
    if (inst.kind === "timer" && inst.mnemonics.includes("RTO") && !reset) {
      add({
        rule: "RTO_NO_RESET",
        severity: "medium",
        title: `Retentive timer ${inst.display} is never reset`,
        description: `${inst.display} is an RTO, which keeps its accumulated time when its rung goes false. Without a RES it reaches its preset once and stays done forever.`,
        recommendation: `Add RES(${inst.display}) on the condition that should restart the timing.`,
        rungs: sortNum(inst.instrIds.map((id) => instrRung(x, id))),
        instrIds: [...inst.instrIds],
        tags: [inst.display],
        confidence: 85,
        basis: "rule",
      });
    }
  }

  for (const { ins, rung } of allInstrs) {
    const ops = ins.operands;
    if (["TON", "TOF", "RTO", "TP"].includes(ins.mnemonic)) {
      const base = { rule: "TIMER_PRESET_INVALID" as const, rungs: [rung.number], instrIds: [ins.id], tags: [ops[0].raw], basis: "rule" as const, standard: "IEC 61131-3" };
      const ms = timerPresetMs(ins);
      const slcPre = ops.length === 4 ? ops[2] : null;
      if (slcPre && slcPre.type === "number" && (slcPre.value! > 32767 || slcPre.value! < 0)) {
        add({
          ...base,
          severity: "high",
          title: `${ops[0].raw} preset ${slcPre.raw} does not fit an SLC timer`,
          description: `SLC 500 / MicroLogix timer presets are 16-bit (0-32767). ${slcPre.raw} will be rejected or wrap, so the timer will not time as intended.`,
          recommendation: "Use a coarser time base (e.g. 1.0 s instead of 0.01 s) or cascade two timers.",
          confidence: 95,
        });
      } else if (ms !== null && ms <= 0) {
        add({
          ...base,
          severity: "high",
          title: `${ops[0].raw} has a preset of ${ms} ms`,
          description: `A ${ins.mnemonic} with a zero or negative preset is done as soon as it is enabled (or faults on some controllers), so the intended delay does not exist.`,
          recommendation: "Set the preset to the intended time and document where it comes from.",
          confidence: 95,
        });
      } else if (ms !== null && ms > 2_147_483_647) {
        add({
          ...base,
          severity: "high",
          title: `${ops[0].raw} preset overflows a DINT`,
          description: `${ms} ms is larger than the 2 147 483 647 ms a 32-bit timer can hold, so the preset will be rejected or wrap.`,
          recommendation: "Reduce the preset or count longer periods with a counter driven by a shorter timer.",
          confidence: 95,
        });
      } else if (ms === null && ops.length !== 4 && ops[1].type === "tag") {
        add({
          ...base,
          severity: "low",
          title: `${ops[0].raw} preset is set at runtime`,
          description: `The preset of ${ops[0].raw} comes from ${ops[1].raw}, so it cannot be checked statically. A zero or negative value would make the timer finish immediately.`,
          recommendation: `Clamp ${ops[1].raw} to a sane range before it reaches the timer and document its source.`,
          confidence: 60,
        });
      }
    }
    if (["CTU", "CTD", "CTUD"].includes(ins.mnemonic) && ops[1].type === "number") {
      const v = ops[1].value!;
      if (v > 2_147_483_647 || v < -2_147_483_648) {
        add({
          rule: "COUNTER_PRESET_INVALID",
          severity: "high",
          title: `${ops[0].raw} preset overflows a DINT`,
          description: `Counter presets are 32-bit; ${ops[1].raw} cannot be stored, so the counter will never reach it.`,
          recommendation: "Reduce the preset or cascade counters.",
          rungs: [rung.number],
          instrIds: [ins.id],
          tags: [ops[0].raw],
          confidence: 95,
          basis: "rule",
        });
      } else if (v <= 0 && ins.mnemonic === "CTU") {
        add({
          rule: "COUNTER_PRESET_INVALID",
          severity: "medium",
          title: `${ops[0].raw} has a preset of ${ops[1].raw}`,
          description: `A count-up counter with a preset of ${ops[1].raw} is done before the first count.`,
          recommendation: "Set the preset to the number of events you want to count.",
          rungs: [rung.number],
          instrIds: [ins.id],
          tags: [ops[0].raw],
          confidence: 90,
          basis: "rule",
        });
      }
    }
    if (ins.mnemonic === "DIV" && ops[1].type === "number" && ops[1].value === 0) {
      add({
        rule: "DIVIDE_BY_ZERO",
        severity: "high",
        title: `Division by zero in rung ${rung.number}`,
        description: `DIV(${ops.map((o) => o.raw).join(",")}) divides by the constant 0. Depending on the controller this sets a math overflow flag, stores a garbage result or raises a major fault.`,
        recommendation: "Divide by the intended constant, or guard a variable divisor with NEQ(divisor,0) on the same rung.",
        rungs: [rung.number],
        instrIds: [ins.id],
        tags: [ops[2].raw],
        confidence: 100,
        basis: "rule",
      });
    }
  }

  // ---------------------------------------------------------------- per-rung condition checks
  const outputsByRung = new Map<number, OutputCondition[]>();
  for (const o of x.outputs) outputsByRung.set(o.rungIndex, [...(outputsByRung.get(o.rungIndex) ?? []), o]);
  rungs.forEach((rung, rungIndex) => {
    const outs = outputsByRung.get(rungIndex) ?? [];
    const instrs = [...iterInstructions(rung.body)];
    const hasAFI = instrs.some((i) => i.mnemonic === "AFI");
    const dead: OutputCondition[] = [];
    const always: OutputCondition[] = [];
    const unconditional: OutputCondition[] = [];
    const dups = new Set<string>();
    const conflicts = new Set<string>();
    for (const o of outs) {
      const a = analyzeExpr(o.condition);
      const ins = x.instructions.get(o.instrId)!.instr;
      if (a.satisfiable === false) {
        dead.push(o);
        continue;
      }
      if (a.tautology === true) {
        const inputsBefore = instrs.some((i) => i.index < ins.index && i.mnemonic !== "LBL" && roleOfMnemonic(i.mnemonic) === "in");
        if (inputsBefore) always.push(o);
        else if (!NO_UNCONDITIONAL.has(o.mnemonic)) unconditional.push(o);
      }
      scanLiterals(o.condition, new Map(), (k) => dups.add(k), (k) => conflicts.add(k));
    }
    const targetsOf = (os: OutputCondition[]) =>
      uniq(os.map((o) => (o.target ? x.table.display(o.target) : o.mnemonic)));
    if (dead.length) {
      add({
        rule: "DEAD_RUNG",
        severity: hasAFI ? "low" : "medium",
        title: hasAFI ? `Rung ${rung.number} is disabled with AFI` : `Rung ${rung.number} can never energize ${targetsOf(dead).join(", ")}`,
        description: hasAFI
          ? `Rung ${rung.number} contains AFI (always false), so its outputs never execute. This is usually left over from commissioning or testing.`
          : `The condition ${exprToString(dead[0].condition)} can never be true, so ${targetsOf(dead).join(", ")} in rung ${rung.number} never energizes.`,
        recommendation: hasAFI ? "Remove the AFI once testing is finished, or delete the rung if it is obsolete." : "Check the contact types and compare limits on this rung; one of them is probably inverted or swapped.",
        rungs: [rung.number],
        instrIds: dead.map((o) => o.instrId),
        tags: targetsOf(dead),
        confidence: 100,
        basis: "rule",
      });
    }
    if (always.length) {
      add({
        rule: "ALWAYS_TRUE",
        severity: "medium",
        title: `Rung ${rung.number} is always true`,
        description: `The inputs on rung ${rung.number} cannot stop power flow (condition reduces to TRUE), so ${targetsOf(always).join(", ")} is energized every scan. Typical causes: an empty branch leg bypassing contacts, a contact in parallel with its own inverse, or a compare of two constants.`,
        recommendation: "Remove the bypass or fix the inverted contact so the rung conditions really gate the output.",
        rungs: [rung.number],
        instrIds: always.map((o) => o.instrId),
        tags: targetsOf(always),
        confidence: 100,
        basis: "rule",
      });
    }
    if (!always.length) {
      const bypassed = bypassedBranches(rung.body);
      if (bypassed.length) {
        const names = uniq(bypassed.flatMap((b) => b.map((i) => i.operands[0]?.raw ?? i.mnemonic)));
        add({
          rule: "BRANCH_BYPASSED",
          severity: "medium",
          title: `An empty branch leg bypasses ${names.join(", ")} in rung ${rung.number}`,
          description: `Rung ${rung.number} has a parallel branch with an empty leg (a plain wire), so the contacts on the other legs (${names.join(", ")}) never affect the rung. A seal-in drawn this way does nothing.`,
          recommendation: "Put the intended contact on the empty leg (for a seal-in: [XIC(Start),XIC(Output)]) or delete the branch.",
          rungs: [rung.number],
          instrIds: bypassed.flat().map((i) => i.id),
          tags: names,
          confidence: 95,
          basis: "rule",
        });
      }
    }
    if (unconditional.length) {
      add({
        rule: "UNCONDITIONAL_OUTPUT",
        severity: "low",
        title: `Rung ${rung.number} has no conditions`,
        description: `${targetsOf(unconditional).join(", ")} on rung ${rung.number} executes every scan with no input instructions in front of it.`,
        recommendation: "Confirm this is intended (e.g. a heartbeat or a constant), otherwise add the missing conditions.",
        rungs: [rung.number],
        instrIds: unconditional.map((o) => o.instrId),
        tags: targetsOf(unconditional),
        confidence: 90,
        basis: "rule",
      });
    }
    if (conflicts.size && dead.length === 0) {
      const names = [...conflicts].map((k) => x.table.display(k.slice(2)));
      add({
        rule: "CONTRADICTORY_CONTACTS",
        severity: "medium",
        title: `Rung ${rung.number} examines ${names.join(", ")} both ways on one path`,
        description: `On one path of rung ${rung.number}, ${names.join(", ")} is examined with XIC and with XIO in series, so that path can never pass power. The rung still works through its other paths, which hides the mistake.`,
        recommendation: "Remove the contradictory contact or move it to the branch where it belongs.",
        rungs: [rung.number],
        instrIds: instrs.filter((i) => (i.mnemonic === "XIC" || i.mnemonic === "XIO") && conflicts.has(`V:${tagKey(i.operands[0].raw)}`)).map((i) => i.id),
        tags: names,
        confidence: 100,
        basis: "rule",
      });
    }
    // a contact repeated after an output that rewrote its tag reads a new value: not redundant
    for (const k of [...dups]) {
      const tag = k.slice(2);
      const reads = instrs.filter((i) => (i.mnemonic === "XIC" || i.mnemonic === "XIO") && tagKey(i.operands[0].raw) === tag).map((i) => i.index);
      const writes = instrs.filter((i) => roleOfMnemonic(i.mnemonic) === "out" && writeTargets(i).includes(tag)).map((i) => i.index);
      if (writes.some((w) => w > Math.min(...reads) && w < Math.max(...reads))) dups.delete(k);
    }
    const legs: string[] = [];
    identicalLegs(rung.body, legs);
    if (dups.size || legs.length) {
      const names = [...dups].map((k) => x.table.display(k.slice(2)));
      const parts = [
        ...(names.length ? [`${names.join(", ")} is examined twice in series on one path`] : []),
        ...(legs.length ? [`a branch has identical legs (${uniq(legs).join(" / ")})`] : []),
      ];
      add({
        rule: "REDUNDANT_CONTACT",
        severity: "low",
        title: `Redundant logic in rung ${rung.number}`,
        description: `On rung ${rung.number}, ${parts.join("; ")}. The duplicate adds scan time and confuses readers without changing behaviour.`,
        recommendation: "Remove the duplicate contact or branch leg.",
        rungs: [rung.number],
        instrIds: instrs.filter((i) => (i.mnemonic === "XIC" || i.mnemonic === "XIO") && dups.has(`V:${tagKey(i.operands[0].raw)}`)).map((i) => i.id),
        tags: names,
        confidence: 95,
        basis: "rule",
      });
    }
  });

  // ---------------------------------------------------------------- heuristics on names
  for (const o of x.outputs) {
    if (o.mnemonic !== "OTE" || !o.target) continue;
    const t = tagOf(o.target)!;
    if (t.hints.includes("indicator")) continue;
    if (!(t.hints.includes("actuator") || t.physical === "output")) continue;
    if (t.writes.some((w) => w.mnemonic === "OTL")) continue;
    const starts = positiveVarTags(o.condition).filter((k) => tagOf(k)?.hints.includes("start"));
    if (!starts.length || hasPositiveVar(o.condition, `V:${o.target}`)) continue;
    if (analyzeExpr(o.condition).satisfiable === false) continue;
    const s = x.table.display(starts[0]);
    add({
      rule: "MISSING_SEAL_IN",
      severity: "medium",
      title: `${t.display} has no seal-in`,
      description: `${t.display} is driven straight from ${s} in rung ${o.rung}. If ${s} is a momentary push-button, ${t.display} runs only while the button is held.`,
      recommendation: `Add a seal-in: put XIC(${t.display}) in parallel with ${s}, i.e. [XIC(${s}),XIC(${t.display})]. Ignore this if ${s} is a maintained switch.`,
      rungs: [o.rung],
      instrIds: [o.instrId],
      tags: [t.display, s],
      confidence: 60,
      basis: "heuristic",
    });
  }

  const interlockSeen = new Set<string>();
  const hasPermissive = (e: Expr) =>
    atomList(e).some((a) => {
      if (a.op === "cmp") return true;
      const key = a.op === "var" ? a.key.slice(2) : a.op === "edge" ? a.tag : "";
      const h = tagOf(key)?.hints ?? [];
      return h.includes("stop") || h.includes("estop") || h.includes("permissive");
    });
  for (const o of x.outputs) {
    if ((o.mnemonic !== "OTE" && o.mnemonic !== "OTL") || !o.target || interlockSeen.has(o.target)) continue;
    const t = tagOf(o.target)!;
    if (!t.hints.includes("actuator")) continue;
    if (analyzeExpr(o.condition).satisfiable === false) continue;
    let ok = hasPermissive(o.condition);
    if (!ok && o.mnemonic === "OTL") {
      ok = x.outputs.some((u) => u.mnemonic === "OTU" && u.target === o.target && hasPermissive(u.condition));
    }
    if (ok) continue;
    interlockSeen.add(o.target);
    add({
      rule: "MISSING_INTERLOCK",
      severity: "medium",
      title: `${t.display} has no visible stop or permissive`,
      description: `${t.display} looks like an actuator, but its ${o.mnemonic === "OTL" ? "latch/unlatch rungs contain" : `condition in rung ${o.rung} (${o.text}) contains`} no stop, trip, overload, limit or permissive signal. If an interlock exists it is not visible in this program.`,
      recommendation: `Add the stop/overload/permissive contacts that must drop ${t.display} out (in series with its condition), or confirm the interlock is implemented elsewhere (hard-wired, safety relay, another routine).`,
      rungs: [o.rung],
      instrIds: [o.instrId],
      tags: [t.display],
      confidence: 55,
      basis: "heuristic",
      standard: "IEC 60204-1",
    });
  }

  const estops = tags.filter((t) => t.hints.includes("estop") && !t.memberOf);
  if (estops.length) {
    const refs = estops.flatMap((t) => [...t.reads, ...t.writes]);
    const esd = estops.some((t) => tagWords(t.display).includes("ESD"));
    add({
      rule: "ESTOP_IN_STANDARD_LOGIC",
      severity: "high",
      title: `Emergency stop handled in standard PLC logic (${estops.map((t) => t.display).join(", ")})`,
      description: `${estops.map((t) => t.display).join(", ")} appears in ${listRungs(refs.map((r) => r.rung))}. An emergency stop must not depend on standard (non-safety) PLC logic: verify that it is a hard-wired or safety-rated function (safety relay or safety PLC) that removes hazardous energy directly, and that these rungs only monitor its status.${esd ? " For a process ESD, that means a separate SIS designed to the required SIL." : ""}`,
      recommendation:
        "Keep the stopping action in the safety-rated circuit; use these rungs for status, alarms and restart interlocks, and make sure resetting the E-stop does not restart the machine by itself.",
      rungs: sortNum(refs.map((r) => r.rung)),
      instrIds: uniq(refs.map((r) => r.instrId)),
      tags: estops.map((t) => t.display),
      confidence: 70,
      basis: "heuristic",
      standard: esd ? "ISO 13850; IEC 60204-1; ISO 13849-1 / IEC 62061; IEC 61511" : "ISO 13850; IEC 60204-1; ISO 13849-1 / IEC 62061",
    });
  }

  for (const t of tags) {
    if (!t.hints.includes("stop") || t.memberOf || t.physical === "internal" || t.physical === "output") continue;
    if (tagWords(t.display).some((w) => COMMAND_WORDS.has(w))) continue;
    const xio = t.reads.filter((r) => r.mnemonic === "XIO");
    if (!xio.length) continue;
    add({
      rule: "STOP_EXAMINED_WITH_XIO",
      severity: "medium",
      title: `${t.display} is examined with XIO`,
      description: `${t.display} is examined with XIO (NC instruction) in ${listRungs(xio.map((r) => r.rung))}, so the logic runs while the bit is 0. If ${t.display} is a field stop device, it must then be wired normally-open, and a broken wire or lost supply looks exactly like "not pressed": the machine cannot be stopped. Fail-safe practice wires stop devices normally-closed (bit = 1 when healthy) and examines them with XIC.`,
      recommendation: `If the device is wired NC, change XIO(${t.display}) to XIC(${t.display}); if it is wired NO, rewire it NC. Ignore this for internal command bits (e.g. an HMI stop request).`,
      rungs: sortNum(xio.map((r) => r.rung)),
      instrIds: xio.map((r) => r.instrId),
      tags: [t.display],
      confidence: 65,
      basis: "heuristic",
      standard: "IEC 60204-1",
    });
  }

  // ---------------------------------------------------------------- scan order and usage
  if (x.scanNotes.length) {
    const names = uniq(x.scanNotes.map((n) => x.table.display(n.tag)));
    add({
      rule: "SCAN_ORDER_DELAY",
      severity: "low",
      title: `${plural(names.length, "tag")} ${names.length === 1 ? "is" : "are"} read before the rung that writes ${names.length === 1 ? "it" : "them"}`,
      description: `${x.scanNotes.map((n) => n.message).join(" ")} This is a one-scan delay; it is usually harmless but matters for edge detection, sequences and interlocks that must act in the same scan.`,
      recommendation: "Move the writing rung above the rungs that read the bit, or accept the delay knowingly.",
      rungs: sortNum(x.scanNotes.map((n) => n.readRung)),
      instrIds: x.scanNotes.map((n) => n.instrId),
      tags: names,
      confidence: 90,
      basis: "rule",
    });
  }

  const unused = tags.filter(
    (t) =>
      t.writes.length > 0 &&
      t.reads.length === 0 &&
      !t.instance &&
      !t.memberOf &&
      t.physical !== "output" &&
      (t.physical === "internal" || t.hints.includes("internal")),
  );
  if (unused.length) {
    add({
      rule: "UNUSED_INTERNAL",
      severity: "low",
      title: `${plural(unused.length, "internal tag")} written but never read`,
      description: `${unused.map((t) => t.display).join(", ")} ${unused.length === 1 ? "is" : "are"} written in this program but never examined. Either the logic that uses ${unused.length === 1 ? "it" : "them"} lives elsewhere (HMI, another routine) or ${unused.length === 1 ? "it is" : "they are"} dead code.`,
      recommendation: "Remove the unused writes, or document which routine/HMI consumes them.",
      rungs: sortNum(unused.flatMap((t) => t.writes.map((w) => w.rung))),
      instrIds: unused.flatMap((t) => t.writes.map((w) => w.instrId)),
      tags: unused.map((t) => t.display),
      confidence: 70,
      basis: "heuristic",
    });
  }

  const undefinedByBase = new Map<string, TagInfo[]>();
  for (const t of tags) {
    if (!t.memberOf || x.instances.has(t.memberOf)) continue;
    const base = tagOf(t.memberOf);
    if (base && base.writes.length) continue;
    const raw = t.display.split(/[./]/).pop()!.toUpperCase();
    if (!STRONG_MEMBERS.has(raw) && !IEC_MEMBER_NAMES.has(raw)) continue;
    undefinedByBase.set(t.memberOf, [...(undefinedByBase.get(t.memberOf) ?? []), t]);
  }
  for (const [baseKey, members] of undefinedByBase) {
    const baseDisplay = splitMember(members[0].display)!.base;
    const slc = /^[TC]\d+:\d+$/i.test(baseDisplay);
    const iecOnly = members.every((m) => IEC_MEMBER_NAMES.has(m.display.split(/[./]/).pop()!.toUpperCase()));
    const refs = members.flatMap((m) => m.reads);
    add({
      rule: "UNDEFINED_TIMER_REFERENCE",
      severity: "medium",
      title: `${baseDisplay} is used but no timer/counter instruction defines it here`,
      description: `${members.map((m) => m.display).join(", ")} ${members.length === 1 ? "is" : "are"} read in ${listRungs(refs.map((r) => r.rung))}, but this program has no ${slc && baseDisplay.toUpperCase().startsWith("C") ? "counter" : "timer or counter"} instruction for ${baseDisplay}. Unless another routine drives it, the bit never changes.`,
      recommendation: `Check the instance name (typos such as T4:1 vs T4:0 are common) or confirm which routine drives ${baseDisplay}.`,
      rungs: sortNum(refs.map((r) => r.rung)),
      instrIds: refs.map((r) => r.instrId),
      tags: [baseDisplay],
      confidence: slc ? 85 : iecOnly ? 55 : 65,
      basis: slc ? "rule" : "heuristic",
    });
    void baseKey;
  }

  // ---------------------------------------------------------------- program flow
  for (const l of x.labels.values()) {
    if (l.jmp.length && !l.lbl.length) {
      add({
        rule: "JUMP_TARGET_MISSING",
        severity: "high",
        title: `JMP(${l.name}) has no matching LBL`,
        description: `${listRungs(l.jmp.map((j) => j.rung))} jumps to ${l.name}, but no LBL(${l.name}) exists in this routine. Logix rejects the routine on verify; other controllers fault or ignore the jump.`,
        recommendation: `Add LBL(${l.name}) as the first instruction of the target rung, or fix the label name.`,
        rungs: sortNum(l.jmp.map((j) => j.rung)),
        instrIds: l.jmp.map((j) => j.instrId),
        tags: [l.name],
        confidence: 100,
        basis: "rule",
      });
    }
    if (l.lbl.length > 1) {
      add({
        rule: "LABEL_DUPLICATE",
        severity: "high",
        title: `LBL(${l.name}) is defined ${l.lbl.length} times`,
        description: `Labels must be unique in a routine; ${listRungs(l.lbl.map((b) => b.rung))} all define ${l.name}, so the jump target is ambiguous.`,
        recommendation: "Rename the duplicate labels so each jump has exactly one target.",
        rungs: sortNum(l.lbl.map((b) => b.rung)),
        instrIds: l.lbl.map((b) => b.instrId),
        tags: [l.name],
        confidence: 100,
        basis: "rule",
      });
    }
    for (const b of l.lbl) {
      if (!b.first) {
        add({
          rule: "LBL_NOT_FIRST",
          severity: "medium",
          title: `LBL(${l.name}) is not the first instruction of rung ${b.rung}`,
          description: "A label must be the first instruction on its rung; anything in front of it is skipped when the jump lands.",
          recommendation: `Move LBL(${l.name}) to the start of rung ${b.rung}.`,
          rungs: [b.rung],
          instrIds: [b.instrId],
          tags: [l.name],
          confidence: 100,
          basis: "rule",
        });
      }
    }
    if (l.lbl.length === 1) {
      for (const j of l.jmp) {
        if (l.lbl[0].rungIndex <= j.rungIndex) {
          add({
            rule: "BACKWARD_JUMP",
            severity: "medium",
            title: `JMP(${l.name}) in rung ${j.rung} jumps backwards`,
            description: `The jump in rung ${j.rung} goes back to rung ${l.lbl[0].rung}. Backward jumps repeat logic inside one scan; if the jump condition never clears, the scan time grows until the watchdog faults the controller.`,
            recommendation: "Prefer forward jumps or a counter-limited loop, and make sure the loop condition always clears.",
            rungs: sortNum([j.rung, l.lbl[0].rung]),
            instrIds: [j.instrId, l.lbl[0].instrId],
            tags: [l.name],
            confidence: 100,
            basis: "rule",
          });
        }
      }
    }
  }

  let mcrOpen: { rung: number; id: string } | null = null;
  for (const { ins, rung } of allInstrs) {
    if (ins.mnemonic !== "MCR") continue;
    const cond = x.instructions.get(ins.id)!.conditionIn;
    const unconditional = cond.op === "const" && cond.value;
    if (!unconditional) {
      if (mcrOpen) {
        add({
          rule: "MCR_UNBALANCED",
          severity: "high",
          title: `MCR zone nested in rung ${rung.number}`,
          description: `The MCR zone opened in rung ${mcrOpen.rung} is still open when rung ${rung.number} starts another one. MCR zones cannot be nested; the inner MCR ends the first zone instead of starting a new one.`,
          recommendation: "Close each zone with an unconditional MCR before starting the next one.",
          rungs: sortNum([mcrOpen.rung, rung.number]),
          instrIds: [mcrOpen.id, ins.id],
          tags: [],
          confidence: 100,
          basis: "rule",
        });
      }
      mcrOpen = { rung: rung.number, id: ins.id };
    } else if (mcrOpen) {
      mcrOpen = null;
    }
  }
  if (mcrOpen) {
    add({
      rule: "MCR_UNBALANCED",
      severity: "high",
      title: `MCR zone opened in rung ${mcrOpen.rung} is never closed`,
      description: `The MCR zone that starts in rung ${mcrOpen.rung} has no closing unconditional MCR, so every rung after it is in the zone and de-energizes when the zone condition is false.`,
      recommendation: "End the zone with a rung that contains only MCR().",
      rungs: [mcrOpen.rung],
      instrIds: [mcrOpen.id],
      tags: [],
      confidence: 100,
      basis: "rule",
    });
  }

  for (const t of tags) {
    const storage = [...t.reads, ...t.writes].filter(
      (r) => ["ONS", "OSR", "OSF"].includes(r.mnemonic) && r.operandIndex === 0,
    );
    const storageInstrs = uniq(storage.map((r) => r.instrId));
    if (!storageInstrs.length) continue;
    const foreign = t.writes.filter((w) => !(["ONS", "OSR", "OSF"].includes(w.mnemonic) && w.operandIndex === 0));
    if (storageInstrs.length < 2 && !foreign.length) continue;
    const ids = uniq([...storageInstrs, ...foreign.map((w) => w.instrId)]);
    add({
      rule: "ONE_SHOT_STORAGE_REUSED",
      severity: "high",
      title: `One-shot storage bit ${t.display} is shared`,
      description: `${t.display} is the storage bit of ${plural(storageInstrs.length, "one-shot")}${foreign.length ? ` and is also written by ${foreign.map((w) => w.mnemonic).join(", ")}` : ""}. A one-shot's storage bit must belong to it alone; otherwise the pulses are missed or fire twice.`,
      recommendation: "Give every ONS/OSR/OSF its own storage bit and never write that bit anywhere else.",
      rungs: sortNum(ids.map((id) => instrRung(x, id))),
      instrIds: ids,
      tags: [t.display],
      confidence: 100,
      basis: "rule",
    });
  }

  // ---------------------------------------------------------------- recognition, comments, naming
  const unknownRefs = allInstrs.filter(({ ins }) => ins.operands.some((o) => o.type === "unknown"));
  if (unknownRefs.length) {
    const n = unknownRefs.reduce((s, { ins }) => s + ins.operands.filter((o) => o.type === "unknown").length, 0);
    add({
      rule: "UNKNOWN_OPERANDS",
      severity: "medium",
      title: `${plural(n, "operand")} could not be read`,
      description: `${plural(n, "operand")} in ${listRungs(unknownRefs.map((u) => u.rung.number))} ${n === 1 ? "is" : "are"} unknown (?), usually because the address was not legible in the image. Findings that depend on ${n === 1 ? "it" : "them"} may be missing or wrong.`,
      recommendation: "Fill in the ? operands from the source program before relying on the analysis.",
      rungs: sortNum(unknownRefs.map((u) => u.rung.number)),
      instrIds: unknownRefs.map((u) => u.ins.id),
      tags: [],
      confidence: 100,
      basis: "rule",
    });
  }

  const uncommented = rungs.filter((r) => !r.comment);
  if (uncommented.length) {
    add({
      rule: "MISSING_COMMENT",
      severity: "low",
      title: `${uncommented.length} of ${rungs.length} rungs have no comment`,
      description: `${listRungs(uncommented.map((r) => r.number))} ${uncommented.length === 1 ? "has" : "have"} no rung comment. Comments are what lets the next engineer (and an audit) see the intent behind each rung.`,
      recommendation: "Add a one-line comment per rung describing what it does and why.",
      rungs: sortNum(uncommented.map((r) => r.number)),
      instrIds: [],
      tags: [],
      confidence: 100,
      basis: "rule",
    });
  }

  const naming = namingReasons(tags);
  if (naming.length) {
    add({
      rule: "NAMING_INCONSISTENCY",
      severity: "low",
      title: "Tag naming is inconsistent",
      description: `${naming.join(" ")} Consistent naming makes cross-references and searches reliable.`,
      recommendation: "Pick one convention (for example Area_Device_Function in one case style) and alias raw I/O addresses to symbolic names.",
      rungs: [],
      instrIds: [],
      tags: [],
      confidence: 80,
      basis: "heuristic",
    });
  }

  // ---------------------------------------------------------------- assemble
  const ordered = drafts
    .map((d, i) => ({ d, i }))
    .sort(
      (a, b) =>
        RANK[a.d.severity] - RANK[b.d.severity] ||
        (a.d.rungs[0] ?? Infinity) - (b.d.rungs[0] ?? Infinity) ||
        a.d.rule.localeCompare(b.d.rule) ||
        a.i - b.i,
    );
  const findings: Finding[] = ordered.map(({ d }, i) => ({
    id: `F${i + 1}`,
    rule: d.rule,
    checklist: d.checklist !== undefined ? d.checklist : (RULE_CHECKLIST[d.rule][0] ?? null),
    severity: d.severity,
    title: d.title,
    description: d.description,
    recommendation: d.recommendation,
    rungs: d.rungs,
    instrIds: d.instrIds,
    tags: d.tags,
    confidence: d.confidence,
    basis: d.basis,
    ...(d.standard ? { standard: d.standard } : {}),
  }));

  const counts = { critical: 0, high: 0, medium: 0, low: 0, total: findings.length };
  for (const f of findings) counts[f.severity]++;
  const { riskScore, grade } = riskOf(findings.map((f) => f.severity));
  return { findings, checklist: buildChecklist(findings, rungs, x, parseErrors), riskScore, grade, counts };
}

/** Input instructions on the non-empty legs of branches that also have an empty leg. */
function bypassedBranches(seq: Seq): Instr[][] {
  const out: Instr[][] = [];
  for (const item of seq.items) {
    if (item.kind !== "branch") continue;
    if (item.legs.some((l) => l.items.length === 0)) {
      const inputs = item.legs.flatMap((l) => [...iterInstructions(l)]).filter((i) => roleOfMnemonic(i.mnemonic) === "in");
      if (inputs.length) out.push(inputs);
    }
    for (const leg of item.legs) out.push(...bypassedBranches(leg));
  }
  return out;
}

const roleOfMnemonic = (m: Mnemonic): "in" | "out" => roleOf(m);

function namingReasons(tags: TagInfo[]): string[] {
  const bases = uniq(tags.filter((t) => !t.memberOf && !t.display.startsWith('"')).map((t) => t.display));
  const isAddress = (d: string) => physicalClass(d) !== "unknown" || /^[TCR]\d*:\d+/i.test(d);
  const addresses = bases.filter(isAddress);
  const symbolic = bases.filter((d) => !isAddress(d));
  const reasons: string[] = [];
  if (addresses.length && symbolic.length) {
    reasons.push(`Raw addresses (${addresses.slice(0, 3).join(", ")}) are mixed with symbolic tags (${symbolic.slice(0, 3).join(", ")}).`);
  }
  const underscore = symbolic.filter((d) => d.includes("_"));
  const camel = symbolic.filter((d) => !d.includes("_") && /[a-z][A-Z]/.test(d));
  if (underscore.length >= 2 && camel.length >= 2) {
    reasons.push(`Underscore names (${underscore.slice(0, 3).join(", ")}) are mixed with CamelCase names (${camel.slice(0, 3).join(", ")}).`);
  }
  return reasons;
}

function buildChecklist(findings: Finding[], rungs: Rung[], x: Xref, parseErrors: ParseError[]): Record<ChecklistKey, ChecklistEntry> {
  const out = {} as Record<ChecklistKey, ChecklistEntry>;
  for (const k of CHECKLIST_KEYS) out[k] = { status: "NOT_FOUND", findings: [] };
  for (const f of findings) {
    for (const k of RULE_CHECKLIST[f.rule]) {
      out[k].status = "FOUND";
      out[k].findings.push(f.id);
    }
  }
  const na = (k: ChecklistKey, reason: string) => {
    if (out[k].status !== "FOUND") out[k] = { status: "NOT_APPLICABLE", reason, findings: [] };
  };
  const mnems = new Set<Mnemonic>();
  for (const r of rungs) for (const i of iterInstructions(r.body)) mnems.add(i.mnemonic);
  const tags = [...x.tags.values()];
  const instances: Instance[] = [...x.instances.values()];
  na("MISSING_SAFETY_INPUT", "Needs SIS/SRS context (the safety requirement specification); it cannot be judged from ladder logic alone.");
  na("BYPASSED_SAFETY", "Needs SIS/SRS context and live force/bypass status; it cannot be judged from ladder logic alone.");
  if (!mnems.has("OTL") && !mnems.has("OTU")) na("LATCH_WITHOUT_UNLATCH", "No OTL/OTU instructions in this program.");
  if (!instances.length) na("TIMER_OVERFLOW", "No timers or counters in this program.");
  if (!instances.some((i) => i.kind === "counter" || i.mnemonics.includes("RTO"))) {
    na("COUNTER_NO_RESET", "No counters or retentive timers in this program.");
  }
  if (!tags.some((t) => t.hints.includes("start"))) na("MISSING_SEAL_IN", "No start/stop circuit recognised by name.");
  if (!tags.some((t) => t.hints.includes("actuator") && t.writes.length)) {
    na("MISSING_INTERLOCK", "No actuator-like outputs recognised by name.");
    na("MISSING_PERMISSIVE", "No actuator-like outputs recognised by name.");
  }
  if (!tags.some((t) => t.hints.includes("stop"))) na("WRONG_CONTACT_TYPE", "No stop devices recognised by name.");
  const unbalanced = parseErrors.filter((e) => e.code === "E_UNBALANCED");
  if (unbalanced.length) {
    out.BROKEN_BRANCH = {
      status: "FOUND",
      reason: `Unbalanced branch or parenthesis at line ${unbalanced.map((e) => e.line).join(", ")} (the rung was not analysed).`,
      findings: [],
    };
  }
  if (!rungs.length) {
    for (const k of CHECKLIST_KEYS) {
      if (out[k].status === "NOT_FOUND") out[k] = { status: "NOT_APPLICABLE", reason: "No rungs to analyse.", findings: [] };
    }
  }
  return out;
}
