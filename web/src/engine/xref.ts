// Signal trace and cross reference.
//
// Walks every rung with the Logix rung-condition model (contract §1.4): input instructions
// AND their test into the condition, output instructions act on it and pass it through, a
// branch ORs its legs. Every instruction gets its rung-condition-in as an expression tree.

import { iterInstructions, roleOf } from "./parse";
import {
  findInstances,
  nameHints,
  physicalClass,
  splitMember,
  TagTable,
  tagKey,
  type Instance,
  type NameHint,
  type Physical,
} from "./tags";
import type { Instr, Mnemonic, Operand, Rung, Seq } from "./types";

// ------------------------------------------------------------------ expressions
export type CmpMnemonic = "EQU" | "NEQ" | "GRT" | "GEQ" | "LES" | "LEQ" | "LIM";

export type Expr =
  | { op: "const"; value: boolean }
  | { op: "var"; key: string; label: string }
  | { op: "cmp"; key: string; mnemonic: CmpMnemonic; operands: Operand[]; label: string }
  | { op: "edge"; key: string; kind: "P" | "N" | "ONS"; tag: string; label: string }
  | { op: "not"; arg: Expr }
  | { op: "and"; args: Expr[] }
  | { op: "or"; args: Expr[] };

export type Atom = Extract<Expr, { op: "var" | "cmp" | "edge" }>;

const TRUE: Expr = { op: "const", value: true };
const FALSE: Expr = { op: "const", value: false };

function and(...xs: Expr[]): Expr {
  const args: Expr[] = [];
  for (const x of xs) {
    if (x.op === "const") {
      if (!x.value) return FALSE;
      continue;
    }
    if (x.op === "and") args.push(...x.args);
    else args.push(x);
  }
  if (args.length === 0) return TRUE;
  return args.length === 1 ? args[0] : { op: "and", args };
}

function or(...xs: Expr[]): Expr {
  const args: Expr[] = [];
  for (const x of xs) {
    if (x.op === "const") {
      if (x.value) return TRUE;
      continue;
    }
    if (x.op === "or") args.push(...x.args);
    else args.push(x);
  }
  if (args.length === 0) return FALSE;
  return args.length === 1 ? args[0] : { op: "or", args };
}

function not(x: Expr): Expr {
  if (x.op === "const") return x.value ? FALSE : TRUE;
  if (x.op === "not") return x.arg;
  return { op: "not", arg: x };
}

/** Expression constructors (simplifying). `E.v(label)` makes a bit variable. */
export const E = {
  t: TRUE,
  f: FALSE,
  and,
  or,
  not,
  v: (label: string): Expr => ({ op: "var", key: `V:${tagKey(label)}`, label }),
};

export function isAtom(e: Expr): e is Atom {
  return e.op === "var" || e.op === "cmp" || e.op === "edge";
}

/** Human-readable condition, e.g. `(Start_PB OR Motor_Run) AND NOT Stop_PB`. */
export function exprToString(e: Expr): string {
  switch (e.op) {
    case "const":
      return e.value ? "TRUE" : "FALSE";
    case "var":
    case "edge":
      return e.label;
    case "cmp":
      return `(${e.label})`;
    case "not":
      return isAtom(e.arg) ? `NOT ${exprToString(e.arg)}` : `NOT (${exprToString(e.arg)})`;
    case "and":
      return e.args.map((a) => (a.op === "or" ? `(${exprToString(a)})` : exprToString(a))).join(" AND ");
    case "or":
      return e.args.map((a) => (a.op === "and" ? `(${exprToString(a)})` : exprToString(a))).join(" OR ");
  }
}

const CMP_SYMBOL: Record<Exclude<CmpMnemonic, "LIM">, string> = {
  EQU: "=",
  NEQ: "<>",
  GRT: ">",
  GEQ: ">=",
  LES: "<",
  LEQ: "<=",
};

function numericValue(o: Operand): number | null {
  return o.type === "number" || o.type === "time" ? (o.value ?? null) : null;
}

function operandKey(o: Operand): string {
  return o.type === "tag" ? tagKey(o.raw) : o.raw;
}

function compareConst(m: Exclude<CmpMnemonic, "LIM">, a: number, b: number): boolean {
  switch (m) {
    case "EQU":
      return a === b;
    case "NEQ":
      return a !== b;
    case "GRT":
      return a > b;
    case "GEQ":
      return a >= b;
    case "LES":
      return a < b;
    case "LEQ":
      return a <= b;
  }
}

// ------------------------------------------------------------------ cross reference types
export interface TagRef {
  rung: number;
  rungIndex: number;
  instrId: string;
  mnemonic: Mnemonic;
  operandIndex: number;
}

export interface TagInfo {
  key: string;
  display: string;
  reads: TagRef[];
  writes: TagRef[];
  physical: Physical;
  hints: NameHint[];
  /** Set when the tag is a timer/counter instance. */
  instance?: "timer" | "counter";
  /** Instance key when the tag is a member access such as T1.DN. */
  memberOf?: string;
}

export interface InstrInfo {
  instr: Instr;
  rung: number;
  rungIndex: number;
  conditionIn: Expr;
  conditionOut: Expr;
}

export interface OutputCondition {
  instrId: string;
  rung: number;
  rungIndex: number;
  mnemonic: Mnemonic;
  /** Tag key written by the instruction (bit for coils, dest for math, instance for timers). */
  target: string | null;
  condition: Expr;
  text: string;
}

export interface Dependency {
  from: string;
  to: string;
  kind: "condition" | "data";
  rung: number;
  instrId: string;
}

export interface ScanNote {
  tag: string;
  readRung: number;
  writeRung: number;
  instrId: string;
  message: string;
}

export interface LabelRefs {
  name: string;
  lbl: { rung: number; rungIndex: number; instrId: string; first: boolean }[];
  jmp: { rung: number; rungIndex: number; instrId: string }[];
}

export interface Xref {
  tags: Map<string, TagInfo>;
  instructions: Map<string, InstrInfo>;
  outputs: OutputCondition[];
  dependencies: Dependency[];
  scanNotes: ScanNote[];
  labels: Map<string, LabelRefs>;
  routines: string[];
  instances: Map<string, Instance>;
  table: TagTable;
}

type Access = "r" | "w" | "rw" | "inst" | "label" | "routine";

/** How each operand of an instruction is used. Missing positions default to read. */
export function operandAccess(ins: Instr, k: number): Access {
  const m = ins.mnemonic;
  switch (m) {
    case "ONS":
      return "rw";
    case "LBL":
    case "JMP":
      return "label";
    case "JSR":
      return k === 0 ? "routine" : "r";
    case "OTE":
    case "OTL":
    case "OTU":
    case "NCOIL":
      return "w";
    case "OSR":
    case "OSF":
      return k === 0 ? "rw" : "w";
    case "TON":
    case "TOF":
    case "RTO":
    case "TP":
    case "CTU":
    case "CTD":
    case "CTUD":
    case "RES":
      return k === 0 ? "inst" : "r";
    case "ADD":
    case "SUB":
    case "MUL":
    case "DIV":
    case "AND":
    case "OR":
    case "XOR":
      return k === 2 ? "w" : "r";
    case "MOV":
    case "NOT":
      return k === 1 ? "w" : "r";
    default:
      return "r";
  }
}

/** Tag keys an instruction writes (coil bit, math destination, one-shot output, instance). */
export function writeTargets(ins: Instr): string[] {
  const out: string[] = [];
  ins.operands.forEach((o, k) => {
    const a = operandAccess(ins, k);
    if (o.type === "tag" && (a === "w" || a === "inst")) out.push(tagKey(o.raw));
  });
  return out;
}

// ------------------------------------------------------------------ the walk
function testExpr(ins: Instr, table: TagTable): Expr {
  const ops = ins.operands;
  const label = (o: Operand) => (o.type === "tag" ? table.display(tagKey(o.raw)) : o.raw);
  switch (ins.mnemonic) {
    case "XIC":
      return { op: "var", key: `V:${tagKey(ops[0].raw)}`, label: label(ops[0]) };
    case "XIO":
      return not({ op: "var", key: `V:${tagKey(ops[0].raw)}`, label: label(ops[0]) });
    case "P":
    case "N":
      return {
        op: "edge",
        key: `E:${ins.mnemonic}:${tagKey(ops[0].raw)}`,
        kind: ins.mnemonic,
        tag: tagKey(ops[0].raw),
        label: `${ins.mnemonic === "P" ? "RISING" : "FALLING"}(${label(ops[0])})`,
      };
    case "ONS":
      return { op: "edge", key: `E:ONS:${tagKey(ops[0].raw)}`, kind: "ONS", tag: tagKey(ops[0].raw), label: `ONESHOT(${label(ops[0])})` };
    case "AFI":
      return FALSE;
    case "LBL":
      return TRUE;
    case "LIM": {
      const [lo, t, hi] = ops;
      const [a, b, c] = [numericValue(lo), numericValue(t), numericValue(hi)];
      if (a !== null && b !== null && c !== null) return a <= c ? (a <= b && b <= c ? TRUE : FALSE) : b >= a || b <= c ? TRUE : FALSE;
      return {
        op: "cmp",
        key: `C:LIM(${ops.map(operandKey).join(",")})`,
        mnemonic: "LIM",
        operands: ops,
        label: `${label(lo)} <= ${label(t)} <= ${label(hi)}`,
      };
    }
    case "EQU":
    case "NEQ":
    case "GRT":
    case "GEQ":
    case "LES":
    case "LEQ": {
      const [x, y] = ops;
      const vx = numericValue(x);
      const vy = numericValue(y);
      if (vx !== null && vy !== null) return compareConst(ins.mnemonic, vx, vy) ? TRUE : FALSE;
      if (x.type === "tag" && y.type === "tag" && tagKey(x.raw) === tagKey(y.raw)) {
        return ["EQU", "GEQ", "LEQ"].includes(ins.mnemonic) ? TRUE : FALSE;
      }
      return {
        op: "cmp",
        key: `C:${ins.mnemonic}(${ops.map(operandKey).join(",")})`,
        mnemonic: ins.mnemonic,
        operands: ops,
        label: `${label(x)} ${CMP_SYMBOL[ins.mnemonic]} ${label(y)}`,
      };
    }
    default:
      return TRUE; // output instructions never reach here (they pass the condition through)
  }
}

/**
 * Walk a sequence. `base` is the condition entering the sequence, `local` grows with the
 * sequence's own inputs; a branch's legs start from TRUE with base AND local as their base,
 * so the result is factored (`c AND (x OR y)`) instead of distributed (`c AND x OR c AND y`)
 * and stays linear in the rung size. Returns the local condition (excluding base).
 */
function walk(seq: Seq, base: Expr, visit: (ins: Instr, condIn: Expr, condOut: Expr) => void, table: TagTable): Expr {
  let local: Expr = TRUE;
  for (const item of seq.items) {
    if (item.kind === "instr") {
      const condIn = and(base, local);
      if (roleOf(item.mnemonic) === "in") local = and(local, testExpr(item, table));
      visit(item, condIn, and(base, local));
    } else {
      const legBase = and(base, local);
      local = and(local, or(...item.legs.map((leg) => walk(leg, legBase, visit, table))));
    }
  }
  return local;
}

function atomTags(e: Expr, out: Set<string>): void {
  switch (e.op) {
    case "var":
      out.add(e.key.slice(2));
      break;
    case "edge":
      out.add(e.tag);
      break;
    case "cmp":
      for (const o of e.operands) if (o.type === "tag") out.add(tagKey(o.raw));
      break;
    case "not":
      atomTags(e.arg, out);
      break;
    case "and":
    case "or":
      for (const a of e.args) atomTags(a, out);
      break;
    default:
      break;
  }
}

/** Tag keys an expression depends on. */
export function exprTags(e: Expr): string[] {
  const s = new Set<string>();
  atomTags(e, s);
  return [...s];
}

export function buildXref(rungs: Rung[], opts: { platform?: string } = {}): Xref {
  const table = new TagTable();
  const tags = new Map<string, TagInfo>();
  const instructions = new Map<string, InstrInfo>();
  const outputs: OutputCondition[] = [];
  const dependencies: Dependency[] = [];
  const labels = new Map<string, LabelRefs>();
  const routines: string[] = [];
  const instances = findInstances(rungs);

  const info = (raw: string): TagInfo => {
    const key = table.see(raw);
    let t = tags.get(key);
    if (!t) {
      const member = splitMember(raw);
      t = {
        key,
        display: table.display(key),
        reads: [],
        writes: [],
        physical: physicalClass(raw, opts.platform),
        hints: nameHints(raw),
      };
      if (member) t.memberOf = tagKey(member.base);
      const inst = instances.get(key);
      if (inst) t.instance = inst.kind;
      tags.set(key, t);
    }
    return t;
  };

  // first pass: register tag spellings in order of appearance
  for (const rung of rungs) {
    for (const ins of iterInstructions(rung.body)) {
      ins.operands.forEach((o, k) => {
        const a = operandAccess(ins, k);
        if (o.type === "tag" && a !== "label" && a !== "routine") info(o.raw);
      });
    }
  }

  rungs.forEach((rung, rungIndex) => {
    walk(
      rung.body,
      TRUE,
      (ins, condIn, condOut) => {
        instructions.set(ins.id, { instr: ins, rung: rung.number, rungIndex, conditionIn: condIn, conditionOut: condOut });
        ins.operands.forEach((o, k) => {
          const a = operandAccess(ins, k);
          const ref: TagRef = { rung: rung.number, rungIndex, instrId: ins.id, mnemonic: ins.mnemonic, operandIndex: k };
          if (a === "label") {
            const key = tagKey(o.raw);
            const l = labels.get(key) ?? { name: o.raw, lbl: [], jmp: [] };
            if (ins.mnemonic === "LBL") l.lbl.push({ rung: rung.number, rungIndex, instrId: ins.id, first: ins.index === 0 });
            else l.jmp.push({ rung: rung.number, rungIndex, instrId: ins.id });
            labels.set(key, l);
            return;
          }
          if (a === "routine") {
            if (!routines.includes(o.raw)) routines.push(o.raw);
            return;
          }
          if (o.type !== "tag") return;
          const t = info(o.raw);
          if (a === "r" || a === "rw") t.reads.push(ref);
          if (a === "w" || a === "rw" || a === "inst") t.writes.push(ref);
        });
        if (roleOf(ins.mnemonic) === "out") {
          const targets = writeTargets(ins);
          outputs.push({
            instrId: ins.id,
            rung: rung.number,
            rungIndex,
            mnemonic: ins.mnemonic,
            target: targets.length ? targets[targets.length - 1] : null,
            condition: condIn,
            text: exprToString(condIn),
          });
          const condTags = exprTags(condIn);
          for (const to of targets) {
            for (const from of condTags) dependencies.push({ from, to, kind: "condition", rung: rung.number, instrId: ins.id });
            ins.operands.forEach((o, k) => {
              if (o.type === "tag" && operandAccess(ins, k) === "r") {
                dependencies.push({ from: tagKey(o.raw), to, kind: "data", rung: rung.number, instrId: ins.id });
              }
            });
          }
        }
      },
      table,
    );
  });

  const rungNumbers = rungs.map((r) => r.number);
  return { tags, instructions, outputs, dependencies, scanNotes: scanOrderNotes(tags, instances, instructions, rungNumbers), labels, routines, instances, table };
}

function scanOrderNotes(
  tags: Map<string, TagInfo>,
  instances: Map<string, Instance>,
  instructions: Map<string, InstrInfo>,
  rungNumbers: number[],
): ScanNote[] {
  const notes: ScanNote[] = [];
  const firstWrite = (t: TagInfo): number | null => {
    if (t.memberOf) {
      const inst = instances.get(t.memberOf);
      if (!inst) return null;
      const idx = inst.instrIds.map((id) => instructions.get(id)!.rungIndex);
      return Math.min(...idx);
    }
    const ws = t.writes.filter((w) => w.mnemonic !== "ONS");
    return ws.length ? Math.min(...ws.map((w) => w.rungIndex)) : null;
  };
  for (const t of tags.values()) {
    const fw = firstWrite(t);
    if (fw === null) continue;
    const seen = new Set<number>();
    for (const r of t.reads) {
      if (r.mnemonic === "ONS" || r.rungIndex >= fw || seen.has(r.rungIndex)) continue;
      seen.add(r.rungIndex);
      const writeRung = rungNumbers[fw];
      notes.push({
        tag: t.key,
        readRung: r.rung,
        writeRung,
        instrId: r.instrId,
        message: `${t.display} is read in rung ${r.rung} but first written in rung ${writeRung}; the read sees the previous scan's value.`,
      });
    }
  }
  return notes;
}
