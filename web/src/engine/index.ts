// LogicLens analysis engine: text in, full deterministic analysis out.
//
//   const a = analyzeProgram("XIC(Start)[XIC(Motor),]XIO(Stop)OTE(Motor);");
//   a.faults.findings, a.st.code, a.corrections.patches ...
//
// Pure: no I/O, no clocks unless you pass `now` (e.g. performance.now) to get timings.

import { suggestCorrections, type Corrections } from "./correct";
import { analyzeFaults, type FaultReport } from "./faults";
import { iterInstructions, parseProgram } from "./parse";
import { toStructuredText, type StResult } from "./st";
import type { ParseResult } from "./types";
import { buildXref, type Xref } from "./xref";

export interface AnalyzeOptions {
  platform?: string;
  /** Free-text context ("conveyor sorting line"); passed through for the LLM layer. */
  context?: string;
  programName?: string;
  /** Printed in the Structured Text header when given. */
  generatedAt?: string;
  /** Clock used for timingsMs; defaults to a constant clock so results stay deterministic. */
  now?: () => number;
}

export interface ProgramStats {
  rungs: number;
  instructions: number;
  tags: number;
  inputs: number;
  outputs: number;
  timers: number;
  counters: number;
  parseErrors: number;
}

export interface Analysis {
  parse: ParseResult;
  xref: Xref;
  faults: FaultReport;
  corrections: Corrections;
  st: StResult;
  stats: ProgramStats;
  timingsMs: { parse: number; xref: number; faults: number; corrections: number; st: number; total: number };
}

const COILS = new Set(["OTE", "OTL", "OTU", "NCOIL"]);

export function analyzeProgram(text: string, opts: AnalyzeOptions = {}): Analysis {
  const now = opts.now ?? (() => 0);
  const t0 = now();
  const parse = parseProgram(text);
  const t1 = now();
  const xref = buildXref(parse.rungs, { platform: opts.platform });
  const t2 = now();
  const faults = analyzeFaults(parse.rungs, parse.errors, { platform: opts.platform, context: opts.context, xref });
  const t3 = now();
  const corrections = suggestCorrections(parse.rungs, faults);
  const t4 = now();
  const st = toStructuredText(parse.rungs, { programName: opts.programName, generatedAt: opts.generatedAt });
  const t5 = now();

  const tags = [...xref.tags.values()];
  const stats: ProgramStats = {
    rungs: parse.rungs.length,
    instructions: parse.rungs.reduce((n, r) => n + [...iterInstructions(r.body)].length, 0),
    tags: tags.filter((t) => !t.memberOf && !t.instance).length,
    inputs: tags.filter((t) => !t.memberOf && !t.instance && t.writes.length === 0).length,
    outputs: tags.filter((t) => t.writes.some((w) => COILS.has(w.mnemonic))).length,
    timers: [...xref.instances.values()].filter((i) => i.kind === "timer").length,
    counters: [...xref.instances.values()].filter((i) => i.kind === "counter").length,
    parseErrors: parse.errors.length,
  };
  return {
    parse,
    xref,
    faults,
    corrections,
    st,
    stats,
    timingsMs: { parse: t1 - t0, xref: t2 - t1, faults: t3 - t2, corrections: t4 - t3, st: t5 - t4, total: t5 - t0 },
  };
}

export * from "./types";
export {
  ALIASES,
  LIMITS,
  SPEC,
  classifyOperand,
  iterInstructions,
  parseProgram,
  parseRungText,
  printProgram,
  printRung,
  printSeq,
  pyRound,
  roleOf,
  timeLiteralMs,
  timerPresetMs,
} from "./parse";
export { TagTable, findInstances, nameHints, physicalClass, splitMember, tagKey, tagWords, type Instance, type Member, type NameHint, type Physical } from "./tags";
export { E, buildXref, exprTags, exprToString, operandAccess, writeTargets, type Atom, type Dependency, type Expr, type InstrInfo, type OutputCondition, type ScanNote, type TagInfo, type TagRef, type Xref } from "./xref";
export { analyzeExpr, atomsOf, feasible, type ExprAnalysis } from "./sat";
export { CHECKLIST_KEYS, analyzeFaults, riskOf, type ChecklistEntry, type ChecklistKey, type FaultOptions, type FaultReport, type Finding, type Grade, type RuleId, type Severity } from "./faults";
export { coerce, inferTypes, toDint, type DataType } from "./datatypes";
export { createSimulator, type CounterState, type InstrPower, type ScanResult, type Simulator, type SimulatorOptions, type TimerState, type Value } from "./simulate";
export { commentSafe, sanitizeIdentifier, toStructuredText, type StOptions, type StResult } from "./st";
export { applyPatches, suggestCorrections, type Advisory, type Applied, type Corrections, type EditOp, type Patch } from "./correct";
