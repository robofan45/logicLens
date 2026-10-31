// IEC 61131-3 Structured Text generator.
//
// Targets the same semantics as simulate.ts (Logix rung-condition model): statements are
// emitted in text order, every function-block instance is called exactly once per scan, and
// rung-condition temporaries appear only when an output in a rung writes a tag that a later
// instruction of the same rung depends on. Output is deterministic (pass generatedAt in).

import { inferTypes } from "./datatypes";
import { iterInstructions, roleOf, timerPresetMs } from "./parse";
import { findInstances, splitMember, tagKey, type Instance, type Member } from "./tags";
import type { Instr, Operand, Rung, Seq } from "./types";
import { buildXref, operandAccess } from "./xref";

export interface StOptions {
  programName?: string;
  /** Printed in the header when given (kept out by default for deterministic output). */
  generatedAt?: string;
}

export interface StResult {
  code: string;
  /** tagKey -> ST identifier for plain tags and timer/counter instances. */
  identifiers: Record<string, string>;
  /** FB type per instance identifier (TON, TOF, TP, TONR, CTU, CTUD). */
  instanceTypes: Record<string, string>;
  /** Constructs that could not be translated exactly (also emitted as comments). */
  warnings: string[];
}

// ------------------------------------------------------------------ identifiers and comments
const RESERVED = new Set(
  (
    "ABS ACTION AND ANY ARRAY AT BOOL BY BYTE CASE CONFIGURATION CONSTANT CTD CTU CTUD DATE DINT DO DT DWORD ELSE ELSIF " +
    "END_ACTION END_CASE END_CONFIGURATION END_FOR END_FUNCTION END_FUNCTION_BLOCK END_IF END_PROGRAM END_REPEAT " +
    "END_RESOURCE END_STEP END_STRUCT END_TRANSITION END_TYPE END_VAR END_WHILE EXIT FALSE FOR FROM FUNCTION " +
    "FUNCTION_BLOCK F_EDGE F_TRIG IF INITIAL_STEP INT INTERVAL LINT LREAL LWORD MOD NOT OF ON OR PRIORITY PROGRAM " +
    "READ_ONLY READ_WRITE REAL REPEAT RESOURCE RETAIN RETURN R_EDGE R_TRIG SINT STEP STRING STRUCT TASK THEN TIME TO " +
    "TOD TOF TON TONR TP TRANSITION TRUE TRUNC TYPE UDINT UINT ULINT UNTIL USINT VAR VAR_ACCESS VAR_EXTERNAL VAR_GLOBAL " +
    "VAR_INPUT VAR_IN_OUT VAR_OUTPUT VAR_TEMP WHILE WITH WORD XOR BOOL_TO_DINT DINT_TO_REAL DINT_TO_TIME TIME_TO_DINT"
  ).split(" "),
);

/** A valid IEC identifier for a tag: [A-Za-z][A-Za-z0-9_]*, no double or trailing underscore. */
export function sanitizeIdentifier(raw: string): string {
  let s = raw.replace(/^"|"$/g, "").replace(/[^A-Za-z0-9_]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  if (!s) s = "TAG";
  if (/^[0-9]/.test(s)) s = `X_${s}`;
  if (RESERVED.has(s.toUpperCase())) s = `${s}_TAG`;
  return s;
}

/** Text that can sit inside (* ... *) without ending or nesting the comment. */
export function commentSafe(text: string): string {
  let s = text.replace(/[\x00-\x1f\x7f]/g, " ");
  const bad = /\(\*|\*\)|\/\*|\*\/|\/\//;
  while (bad.test(s)) s = s.replace(/\(\*/g, "( *").replace(/\*\)/g, "* )").replace(/\/\*/g, "/ *").replace(/\*\//g, "* /").replace(/\/\//g, "/ /");
  return s;
}

class Names {
  private readonly used = new Set<string>();
  alloc(base: string): string {
    const clean = sanitizeIdentifier(base);
    let name = clean;
    let n = 2;
    while (this.used.has(name.toUpperCase())) name = `${clean}_${n++}`;
    this.used.add(name.toUpperCase());
    return name;
  }
}

// ------------------------------------------------------------------ boolean expressions
type SX = { k: "c"; v: boolean } | { k: "a"; s: string } | { k: "not"; x: SX } | { k: "and"; xs: SX[] } | { k: "or"; xs: SX[] };

const T: SX = { k: "c", v: true };
const F: SX = { k: "c", v: false };
const atom = (s: string): SX => ({ k: "a", s });

function sAnd(...xs: SX[]): SX {
  const out: SX[] = [];
  for (const x of xs) {
    if (x.k === "c") {
      if (!x.v) return F;
      continue;
    }
    if (x.k === "and") out.push(...x.xs);
    else out.push(x);
  }
  return out.length === 0 ? T : out.length === 1 ? out[0] : { k: "and", xs: out };
}

function sOr(...xs: SX[]): SX {
  const out: SX[] = [];
  for (const x of xs) {
    if (x.k === "c") {
      if (x.v) return T;
      continue;
    }
    if (x.k === "or") out.push(...x.xs);
    else out.push(x);
  }
  return out.length === 0 ? F : out.length === 1 ? out[0] : { k: "or", xs: out };
}

function sNot(x: SX): SX {
  if (x.k === "c") return x.v ? F : T;
  if (x.k === "not") return x.x;
  return { k: "not", x };
}

function render(x: SX, parent = 0): string {
  switch (x.k) {
    case "c":
      return x.v ? "TRUE" : "FALSE";
    case "a":
      return x.s;
    case "not":
      return `NOT ${render(x.x, 3)}`;
    case "and": {
      const s = x.xs.map((y) => render(y, 2)).join(" AND ");
      return parent > 2 ? `(${s})` : s;
    }
    case "or": {
      const s = x.xs.map((y) => render(y, 1)).join(" OR ");
      return parent > 1 ? `(${s})` : s;
    }
  }
}


// ------------------------------------------------------------------ numbers and time
function fmtNumber(v: number, real: boolean): string {
  if (!Number.isFinite(v)) return real ? "0.0" : "0";
  if (Number.isInteger(v) && !real) return String(v);
  if (Number.isInteger(v) && Math.abs(v) < 1e15) return `${v}.0`;
  const s = String(v);
  if (!s.includes("e")) return s;
  const [m, e] = s.split("e");
  return `${m.includes(".") ? m : `${m}.0`}E${Number(e)}`;
}

function fmtTime(ms: number): string {
  if (ms <= 0) return "T#0ms";
  if (Number.isInteger(ms) && ms % 1000 === 0) return `T#${ms / 1000}s`;
  return `T#${ms}ms`;
}

// ------------------------------------------------------------------ generator
type Num = { s: string; t: "BOOL" | "DINT" | "REAL" };

export function toStructuredText(rungs: Rung[], opts: StOptions = {}): StResult {
  const instances = findInstances(rungs);
  const types = inferTypes(rungs, instances);
  const xref = buildXref(rungs);
  const names = new Names();
  const warnings: string[] = [];
  let sawUnknown = false;
  const ident = new Map<string, string>();
  const display = new Map<string, string>();
  const decls: { name: string; type: string; note: string }[] = [];

  // plain tags in order of appearance, then instances
  for (const rung of rungs) {
    for (const ins of iterInstructions(rung.body)) {
      ins.operands.forEach((o) => {
        if (o.type !== "tag") return;
        const key = tagKey(o.raw);
        if (!display.has(key)) display.set(key, o.raw);
      });
    }
  }
  for (const [key, type] of types) {
    const name = names.alloc(display.get(key)!);
    ident.set(key, name);
    decls.push({ name, type, note: display.get(key)! });
  }
  const fbType = new Map<string, string>();
  for (const inst of instances.values()) {
    const name = names.alloc(inst.display);
    ident.set(inst.key, name);
    let t: string;
    if (inst.kind === "timer") t = { TON: "TON", TOF: "TOF", TP: "TP", RTO: "TONR" }[inst.mnemonics[0] as "TON"] ?? "TON";
    else t = inst.mnemonics.includes("CTD") || inst.mnemonics.includes("CTUD") ? "CTUD" : "CTU";
    fbType.set(inst.key, t);
    decls.push({ name, type: t, note: `${inst.display}${t === "TONR" ? " - retentive timer: TONR is vendor-specific (e.g. Siemens); CODESYS users need an equivalent" : ""}` });
  }
  const rstName = new Map<string, string>();
  for (const inst of instances.values()) {
    if (!inst.resets.length) continue;
    const n = names.alloc(`${ident.get(inst.key)}_RST`);
    rstName.set(inst.key, n);
    decls.push({ name: n, type: "BOOL", note: `RES(${inst.display}) request` });
  }
  // Rockwell CTU + CTD on one counter: the conditions meet in one CTUD call
  const splitCounter = new Map<string, { cu: string; cd: string; callAt: string }>();
  for (const inst of instances.values()) {
    if (inst.kind === "counter" && inst.mnemonics.includes("CTU") && inst.mnemonics.includes("CTD")) {
      const cu = names.alloc(`${ident.get(inst.key)}_CU`);
      const cd = names.alloc(`${ident.get(inst.key)}_CD`);
      decls.push({ name: cu, type: "BOOL", note: `count-up condition of ${inst.display}` });
      decls.push({ name: cd, type: "BOOL", note: `count-down condition of ${inst.display}` });
      splitCounter.set(inst.key, { cu, cd, callAt: inst.instrIds[inst.instrIds.length - 1] });
    }
  }
  const helper = (base: string, type: string, note: string) => {
    const n = names.alloc(base);
    decls.push({ name: n, type, note });
    return n;
  };

  // ---------------------------------------------------------------- operand rendering
  const memberOf = (raw: string): { inst: Instance; member: Member } | null => {
    const m = splitMember(raw);
    if (!m) return null;
    const inst = instances.get(tagKey(m.base));
    return inst ? { inst, member: m.member } : null;
  };

  function memberBit(inst: Instance, member: Member): SX {
    const n = ident.get(inst.key)!;
    const t = fbType.get(inst.key)!;
    if (inst.kind === "timer") {
      if (member === "DN") return atom(`${n}.Q`);
      if (member === "EN") return atom(`${n}.IN`);
      if (member === "TT") return t === "TOF" ? sAnd(sNot(atom(`${n}.IN`)), atom(`${n}.Q`)) : t === "TP" ? atom(`${n}.Q`) : sAnd(atom(`${n}.IN`), sNot(atom(`${n}.Q`)));
      if (member === "ACC" || member === "PRE") return atom(`(${memberNum(inst, member).s} <> 0)`);
      return F;
    }
    if (member === "DN") return atom(t === "CTUD" ? `${n}.QU` : `${n}.Q`);
    if (member === "CU") return atom(`${n}.CU`);
    if (member === "CD") return t === "CTUD" ? atom(`${n}.CD`) : F;
    if (member === "ACC" || member === "PRE") return atom(`(${memberNum(inst, member).s} <> 0)`);
    return F;
  }

  function memberNum(inst: Instance, member: Member): Num {
    const n = ident.get(inst.key)!;
    if (inst.kind === "timer") {
      if (member === "ACC") return { s: `TIME_TO_DINT(${n}.ET)`, t: "DINT" };
      if (member === "PRE") return { s: `TIME_TO_DINT(${n}.PT)`, t: "DINT" };
      return { s: `BOOL_TO_DINT(${render(memberBit(inst, member))})`, t: "DINT" };
    }
    if (member === "ACC") return { s: `${n}.CV`, t: "DINT" };
    if (member === "PRE") return { s: `${n}.PV`, t: "DINT" };
    return { s: `BOOL_TO_DINT(${render(memberBit(inst, member), 3)})`, t: "DINT" };
  }

  function bit(o: Operand): SX {
    if (o.type === "unknown") {
      sawUnknown = true;
      return F;
    }
    if (o.type !== "tag") return o.value ? T : F;
    const m = memberOf(o.raw);
    if (m) return memberBit(m.inst, m.member);
    const key = tagKey(o.raw);
    if (instances.has(key) || !ident.has(key)) return F;
    const n = ident.get(key)!;
    return types.get(key) === "BOOL" ? atom(n) : atom(`(${n} <> 0)`);
  }

  function numeric(o: Operand): Num {
    if (o.type === "unknown") {
      sawUnknown = true;
      return { s: "0", t: "DINT" };
    }
    if (o.type === "number" || o.type === "time") {
      const v = o.value ?? 0;
      if (o.type === "number" && /^\d+#/.test(o.raw)) return { s: o.raw, t: "DINT" };
      return Number.isInteger(v) ? { s: fmtNumber(v, false), t: "DINT" } : { s: fmtNumber(v, true), t: "REAL" };
    }
    const m = memberOf(o.raw);
    if (m) return memberNum(m.inst, m.member);
    const key = tagKey(o.raw);
    if (instances.has(key) || !types.has(key)) return { s: "0", t: "DINT" };
    return { s: ident.get(key)!, t: types.get(key)! };
  }

  const asReal = (x: Num): string =>
    x.t === "REAL" ? x.s : x.t === "DINT" ? (/^-?\d+$/.test(x.s) ? `${x.s}.0` : `DINT_TO_REAL(${x.s})`) : `DINT_TO_REAL(BOOL_TO_DINT(${x.s}))`;
  const asDint = (x: Num): string => (x.t === "DINT" ? x.s : x.t === "REAL" ? `TRUNC(${x.s})` : `BOOL_TO_DINT(${x.s})`);
  const domain = (...xs: Num[]): "REAL" | "DINT" => (xs.some((x) => x.t === "REAL") ? "REAL" : "DINT");
  const inDomain = (d: "REAL" | "DINT", x: Num) => (d === "REAL" ? asReal(x) : asDint(x));

  function assignNum(dest: Operand, value: Num): string {
    if (dest.type !== "tag" || instances.has(tagKey(dest.raw))) return `(* write to ${commentSafe(dest.raw)} not translated *)`;
    const m = memberOf(dest.raw);
    if (m) {
      warnings.push(`Writing ${dest.raw} (a timer/counter member) is not translated`);
      return `(* write to ${commentSafe(dest.raw)} not translated *)`;
    }
    const key = tagKey(dest.raw);
    const n = ident.get(key)!;
    const t = types.get(key) ?? "BOOL";
    if (t === "BOOL") return `${n} := ${value.t === "BOOL" ? value.s : `(${inDomain(domain(value), value)} <> ${value.t === "REAL" ? "0.0" : "0"})`};`;
    if (t === "DINT") return `${n} := ${asDint(value)};`;
    return `${n} := ${asReal(value)};`;
  }

  function assignBit(dest: Operand, cond: SX): string {
    if (dest.type !== "tag" || instances.has(tagKey(dest.raw))) return `(* write to ${commentSafe(dest.raw)} not translated *)`;
    const m = memberOf(dest.raw);
    if (m) {
      warnings.push(`Writing ${dest.raw} (a timer/counter member) is not translated`);
      return `(* write to ${commentSafe(dest.raw)} not translated *)`;
    }
    const key = tagKey(dest.raw);
    const n = ident.get(key)!;
    const t = types.get(key) ?? "BOOL";
    if (t === "BOOL") return `${n} := ${render(cond)};`;
    const d = `BOOL_TO_DINT(${render(cond)})`;
    return t === "DINT" ? `${n} := ${d};` : `${n} := DINT_TO_REAL(${d});`;
  }

  function cmpSX(ins: Instr): SX {
    const sym: Record<string, string> = { EQU: "=", NEQ: "<>", GRT: ">", GEQ: ">=", LES: "<", LEQ: "<=" };
    if (ins.mnemonic === "LIM") {
      const [lo, t, hi] = ins.operands.map(numeric);
      const d = domain(lo, t, hi);
      const [a, b, c] = [inDomain(d, lo), inDomain(d, t), inDomain(d, hi)];
      const l = ins.operands[0];
      const h = ins.operands[2];
      if ((l.type === "number" || l.type === "time") && (h.type === "number" || h.type === "time") && (l.value ?? 0) > (h.value ?? 0)) {
        return atom(`((${b} >= ${a}) OR (${b} <= ${c}))`);
      }
      if (l.type === "tag" || h.type === "tag") {
        return atom(`(((${a} <= ${c}) AND (${a} <= ${b}) AND (${b} <= ${c})) OR ((${a} > ${c}) AND ((${b} >= ${a}) OR (${b} <= ${c}))))`);
      }
      return atom(`((${a} <= ${b}) AND (${b} <= ${c}))`);
    }
    const [x, y] = ins.operands.map(numeric);
    const d = domain(x, y);
    return atom(`(${inDomain(d, x)} ${sym[ins.mnemonic]} ${inDomain(d, y)})`);
  }

  // ---------------------------------------------------------------- statements per instruction
  const called = new Set<string>();
  const edgeName = new Map<string, string>();

  function ifStmt(cond: SX, body: string[]): string[] {
    if (cond.k === "c") return cond.v ? body : [];
    return [`IF ${render(cond)} THEN`, ...body.map((l) => `  ${l}`), "END_IF;"];
  }

  function presetTime(ins: Instr): string {
    const ms = timerPresetMs(ins);
    if (ms !== null) return fmtTime(ms);
    const op = ins.operands.length === 4 ? ins.operands[2] : ins.operands[1];
    if (op.type === "tag") return `DINT_TO_TIME(${asDint(numeric(op))})`;
    sawUnknown = true;
    return "T#0ms (* ? unread preset *)";
  }

  function outputStmts(ins: Instr, cond: SX, rungNo: number, jumpFlags: Map<string, string>, zoneFlags: Map<string, string>): string[] {
    const ops = ins.operands;
    switch (ins.mnemonic) {
      case "OTE":
        return [assignBit(ops[0], cond)];
      case "NCOIL":
        return [assignBit(ops[0], sNot(cond))];
      case "OTL":
        return ifStmt(cond, [assignBit(ops[0], T)]);
      case "OTU":
        return ifStmt(cond, [assignBit(ops[0], F)]);
      case "OSR":
      case "OSF": {
        const fb = edgeName.get(ins.id) ?? helper(`${ins.mnemonic}_${ins.id}`, ins.mnemonic === "OSR" ? "R_TRIG" : "F_TRIG", `${ins.mnemonic}(${commentSafe(ops.map((o) => o.raw).join(","))}) rung ${rungNo}`);
        edgeName.set(ins.id, fb);
        // storage before output: the output may be a tag the condition reads
        return [`${fb}(CLK := ${render(cond)});`, assignBit(ops[0], cond), assignBit(ops[1], atom(`${fb}.Q`))];
      }
      case "TON":
      case "TOF":
      case "TP":
      case "RTO": {
        const key = tagKey(ops[0].raw);
        const n = ident.get(key)!;
        if (called.has(key)) {
          warnings.push(`${ops[0].raw} is driven by more than one timer instruction; only the first (rung ${xref.instructions.get(instances.get(key)!.instrIds[0])!.rung}) is translated`);
          return [`(* ${ins.mnemonic}(${commentSafe(ops[0].raw)}) in rung ${rungNo}: instance already called this scan - not translated *)`];
        }
        called.add(key);
        const rst = rstName.get(key);
        const t = fbType.get(key)!;
        if (t === "TONR") return [`${n}(IN := ${render(cond)}, R := ${rst ?? "FALSE"}, PT := ${presetTime(ins)});`];
        if (rst && t === "TON") {
          return [`${n}(IN := ${render(sAnd(cond, sNot(atom(rst))))}, PT := ${presetTime(ins)}); (* RES gates IN; a RES rung below this one acts on the next scan *)`];
        }
        if (rst) warnings.push(`RES(${ops[0].raw}) on a ${t} has no IEC equivalent and is not translated`);
        return [`${n}(IN := ${render(cond)}, PT := ${presetTime(ins)});${rst ? ` (* RES on ${t} not translatable *)` : ""}`];
      }
      case "CTU":
      case "CTD":
      case "CTUD": {
        const key = tagKey(ops[0].raw);
        const n = ident.get(key)!;
        const rst = rstName.get(key) ?? "FALSE";
        const pv = asDint(numeric(ops[1]));
        const split = splitCounter.get(key);
        if (split) {
          const mine = ins.mnemonic === "CTU" ? split.cu : split.cd;
          const out = [`${mine} := ${render(cond)};`];
          if (split.callAt === ins.id) {
            out.push(`${n}(CU := ${split.cu}, CD := ${split.cd}, R := ${rst}, PV := ${pv}); (* CTU and CTD of ${commentSafe(ops[0].raw)} meet in one CTUD call *)`);
          }
          return out;
        }
        if (called.has(key)) {
          warnings.push(`${ops[0].raw} is driven by more than one counter instruction; only the first is translated`);
          return [`(* ${ins.mnemonic}(${commentSafe(ops[0].raw)}) in rung ${rungNo}: instance already called this scan - not translated *)`];
        }
        called.add(key);
        if (fbType.get(key) === "CTU") return [`${n}(CU := ${render(cond)}, R := ${rst}, PV := ${pv});`];
        if (ins.mnemonic === "CTD") return [`${n}(CU := FALSE, CD := ${render(cond)}, R := ${rst}, PV := ${pv}); (* Logix CTD: DN = ACC >= PRE, mapped to QU *)`];
        const down = ops[2] ? render(bit(ops[2])) : "FALSE";
        return [`${n}(CU := ${render(cond)}, CD := ${down}, R := ${rst}, PV := ${pv});`];
      }
      case "RES": {
        const r = rstName.get(tagKey(ops[0].raw));
        if (!r) return [`(* RES(${commentSafe(ops[0].raw)}) has no timer/counter in this program *)`];
        return [`${r} := ${render(cond)};`];
      }
      case "ADD":
      case "SUB":
      case "MUL":
      case "DIV": {
        const a = numeric(ops[0]);
        const b = numeric(ops[1]);
        const d = domain(a, b, numeric(ops[2]));
        const sym = { ADD: "+", SUB: "-", MUL: "*", DIV: "/" }[ins.mnemonic];
        const val: Num = { s: `${inDomain(d, a)} ${sym} ${inDomain(d, b)}`, t: d };
        const wrapped: Num = { s: `(${val.s})`, t: d };
        if (ins.mnemonic === "DIV" && !((ops[1].type === "number" || ops[1].type === "time") && ops[1].value !== 0)) {
          const zero: Num = { s: d === "REAL" ? "0.0" : "0", t: d };
          return ifStmt(cond, [`IF ${inDomain(d, b)} <> ${zero.s} THEN`, `  ${assignNum(ops[2], wrapped)}`, "ELSE", `  ${assignNum(ops[2], zero)}`, "END_IF;"]);
        }
        return ifStmt(cond, [assignNum(ops[2], wrapped)]);
      }
      case "AND":
      case "OR":
      case "XOR": {
        const val: Num = { s: `(${asDint(numeric(ops[0]))} ${ins.mnemonic} ${asDint(numeric(ops[1]))})`, t: "DINT" };
        return ifStmt(cond, [assignNum(ops[2], val)]);
      }
      case "NOT":
        return ifStmt(cond, [assignNum(ops[1], { s: `(NOT ${asDint(numeric(ops[0]))})`, t: "DINT" })]);
      case "MOV": {
        const src = ops[0].type === "tag" && types.get(tagKey(ops[0].raw)) === "BOOL" && !memberOf(ops[0].raw) ? { s: ident.get(tagKey(ops[0].raw))!, t: "BOOL" as const } : numeric(ops[0]);
        return ifStmt(cond, [assignNum(ops[1], src)]);
      }
      case "JMP": {
        const flag = jumpFlags.get(ins.id);
        return flag ? [`${flag} := ${render(cond)};`] : [`(* JMP(${commentSafe(ops[0].raw)}) not translated (backward or missing label) *)`];
      }
      case "JSR":
        warnings.push(`JSR(${ops[0].raw}) is not translated`);
        return [`(* JSR ${commentSafe(ops.map((o) => o.raw).join(", "))} when ${commentSafe(render(cond))}: call the routine here - not translated *)`];
      case "MCR": {
        const flag = zoneFlags.get(ins.id);
        return flag ? [`${flag} := ${render(cond)};`] : [];
      }
      default:
        return []; // END, NOP
    }
  }

  // ---------------------------------------------------------------- rung codegen
  function readsOf(ins: Instr): Set<string> {
    const s = new Set<string>();
    ins.operands.forEach((o, k) => {
      if (o.type !== "tag") return;
      const a = operandAccess(ins, k);
      if (a === "r" || a === "rw") {
        const m = splitMember(o.raw);
        s.add(m && instances.has(tagKey(m.base)) ? tagKey(m.base) : tagKey(o.raw));
      }
    });
    return s;
  }

  function writesOf(ins: Instr): Set<string> {
    const s = new Set<string>();
    ins.operands.forEach((o, k) => {
      if (o.type !== "tag") return;
      const a = operandAccess(ins, k);
      if (a === "w" || a === "rw" || a === "inst") s.add(tagKey(o.raw));
    });
    return s;
  }

  /**
   * True when an output writes a tag that a later statement of the rung depends on: either a
   * later instruction reads it, or it was read earlier and feeds a later output's condition
   * (simple mode recomputes each output's condition at the output, so it would see the new value).
   */
  function needsTemps(rung: Rung): boolean {
    const written = new Set<string>();
    const readsSoFar = new Set<string>();
    for (const ins of iterInstructions(rung.body)) {
      const reads = readsOf(ins);
      for (const r of reads) if (written.has(r)) return true;
      if (ins.mnemonic === "ONS") {
        // its own storage read is part of the edge detection; the storage write is visible later
        written.add(tagKey(ins.operands[0].raw));
        continue;
      }
      if (roleOf(ins.mnemonic) === "in") {
        for (const r of reads) readsSoFar.add(r);
        continue;
      }
      for (const r of readsSoFar) if (written.has(r)) return true;
      for (const w of writesOf(ins)) written.add(w);
    }
    return false;
  }

  function inputTest(ins: Instr, condIn: SX, pre: string[], rungNo: number): SX {
    const ops = ins.operands;
    switch (ins.mnemonic) {
      case "XIC":
        return bit(ops[0]);
      case "XIO":
        return sNot(bit(ops[0]));
      case "P":
      case "N": {
        const fb =
          edgeName.get(ins.id) ??
          helper(`${ins.mnemonic === "P" ? "RT" : "FT"}_${ins.id}`, ins.mnemonic === "P" ? "R_TRIG" : "F_TRIG", `${ins.mnemonic}(${commentSafe(ops[0].raw)}) rung ${rungNo}`);
        edgeName.set(ins.id, fb);
        pre.push(`${fb}(CLK := ${render(bit(ops[0]))});`);
        return atom(`${fb}.Q`);
      }
      case "ONS": {
        const fb = edgeName.get(ins.id) ?? helper(`ONS_${ins.id}`, "R_TRIG", `ONS(${commentSafe(ops[0].raw)}) rung ${rungNo}`);
        edgeName.set(ins.id, fb);
        // the R_TRIG does the edge detection; the storage bit is kept in step for HMIs/other routines
        pre.push(`${fb}(CLK := ${render(condIn)});`, assignBit(ops[0], condIn));
        return atom(`${fb}.Q`);
      }
      case "AFI":
        return F;
      case "LBL":
        return T;
      default:
        return cmpSX(ins);
    }
  }

  function genRung(rung: Rung, base: SX, jumpFlags: Map<string, string>, zoneFlags: Map<string, string>): string[] {
    const out: string[] = [];
    if (!needsTemps(rung)) {
      const pre: string[] = [];
      const stmts: string[] = [];
      const walk = (seq: Seq, b: SX): SX => {
        let local: SX = T;
        for (const item of seq.items) {
          if (item.kind === "instr") {
            const condIn = sAnd(b, local);
            if (roleOf(item.mnemonic) === "in") local = sAnd(local, inputTest(item, condIn, pre, rung.number));
            else stmts.push(...outputStmts(item, condIn, rung.number, jumpFlags, zoneFlags));
          } else {
            const legBase = sAnd(b, local);
            local = sAnd(local, sOr(...item.legs.map((l) => walk(l, legBase))));
          }
        }
        return local;
      };
      walk(rung.body, base);
      out.push(...pre, ...stmts);
      return out;
    }
    // exact sequential form with rung-condition temporaries: every intermediate rung condition
    // is captured in a temporary when it is computed, so later writes in the rung cannot change it
    let tmp = 0;
    const temps = new Set<string>();
    const temp = (x: SX): SX => {
      if (x.k === "c" || (x.k === "a" && temps.has(x.s))) return x;
      const n = helper(`RC_${rung.number}_${++tmp}`, "BOOL", `rung ${rung.number} condition temporary`);
      temps.add(n);
      out.push(`${n} := ${render(x)};`);
      return atom(n);
    };
    const gen = (seq: Seq, cin: SX): SX => {
      let cur = cin;
      for (const item of seq.items) {
        if (item.kind === "instr") {
          if (roleOf(item.mnemonic) === "in") {
            const pre: string[] = [];
            const test = inputTest(item, cur, pre, rung.number);
            out.push(...pre);
            cur = temp(sAnd(cur, test));
          } else out.push(...outputStmts(item, cur, rung.number, jumpFlags, zoneFlags));
        } else {
          const legs = item.legs.map((l) => gen(l, cur));
          cur = temp(sOr(...legs));
        }
      }
      return cur;
    };
    gen(rung.body, base);
    return out;
  }

  // ---------------------------------------------------------------- program structure
  const endIndex = rungs.findIndex((r) => [...iterInstructions(r.body)].some((i) => i.mnemonic === "END"));
  const last = endIndex >= 0 ? endIndex : rungs.length - 1;
  const labelIdx = new Map<string, number>();
  rungs.forEach((r, idx) => {
    for (const i of iterInstructions(r.body)) if (i.mnemonic === "LBL" && !labelIdx.has(tagKey(i.operands[0].raw))) labelIdx.set(tagKey(i.operands[0].raw), idx);
  });
  const jumpFlags = new Map<string, string>();
  const guards: string[][] = rungs.map(() => []);
  rungs.forEach((r, idx) => {
    for (const i of iterInstructions(r.body)) {
      if (i.mnemonic !== "JMP") continue;
      const target = labelIdx.get(tagKey(i.operands[0].raw));
      if (target === undefined || target <= idx) {
        warnings.push(`JMP(${i.operands[0].raw}) in rung ${r.number} is ${target === undefined ? "missing its label" : "a backward jump"} and is not translated`);
        continue;
      }
      const flag = helper(`JMP_${i.operands[0].raw}_${r.number}`, "BOOL", `JMP(${commentSafe(i.operands[0].raw)}) in rung ${r.number}`);
      jumpFlags.set(i.id, flag);
      for (let k = idx + 1; k < target; k++) guards[k].push(flag);
    }
  });
  // MCR zones: conditional MCR opens, unconditional MCR closes
  const zoneFlags = new Map<string, string>();
  const zoneStart = new Map<number, string>();
  const zoneEnd = new Set<number>();
  const inZone: (string | null)[] = rungs.map(() => null);
  let open: string | null = null;
  rungs.forEach((r, idx) => {
    for (const i of iterInstructions(r.body)) {
      if (i.mnemonic !== "MCR") continue;
      const c = xref.instructions.get(i.id)!.conditionIn;
      const unconditional = c.op === "const" && c.value;
      if (!unconditional) {
        if (open) zoneEnd.add(idx);
        open = helper(`MCR_${r.number}`, "BOOL", `MCR zone opened in rung ${r.number}`);
        zoneFlags.set(i.id, open);
        zoneStart.set(idx, open);
      } else if (open) {
        zoneEnd.add(idx);
        open = null;
      }
    }
    if (open && !zoneStart.has(idx)) inZone[idx] = open;
  });

  const body: string[] = [];
  if (jumpFlags.size) body.push(...[...jumpFlags.values()].map((f) => `${f} := FALSE;`));
  const indent = (ls: string[], n = 1) => ls.map((l) => `${"  ".repeat(n)}${l}`);
  let k = 0;
  while (k <= last && k < rungs.length) {
    const zone = inZone[k];
    if (zone) {
      // collect the whole zone
      const zoneRungs: number[] = [];
      while (k <= last && inZone[k] === zone) zoneRungs.push(k++);
      const live: string[] = [];
      const dead: string[] = [];
      const before = new Set(called);
      for (const idx of zoneRungs) live.push(...rungBlock(idx, T));
      const afterLive = new Set(called);
      called.clear();
      for (const c of before) called.add(c);
      for (const idx of zoneRungs) dead.push(...rungBlock(idx, F));
      for (const c of afterLive) called.add(c);
      body.push(`IF ${zone} THEN`, ...indent(live), "ELSE", `  (* zone off: rungs scanned as false *)`, ...indent(dead), "END_IF;");
      continue;
    }
    body.push(...rungBlock(k, T));
    if (zoneEnd.has(k) && !zoneStart.has(k)) body.push(`(* end of MCR zone *)`);
    k++;
  }
  if (endIndex >= 0 && endIndex < rungs.length - 1) body.push(`(* END in rung ${rungs[endIndex].number}: ${rungs.length - 1 - endIndex} rung(s) after it are not translated *)`);
  if (open) warnings.push("An MCR zone is never closed; it is closed at the end of the program");

  function rungBlock(idx: number, base: SX): string[] {
    const r = rungs[idx];
    const head: string[] = [`(* Rung ${r.number}${r.comment ? `: ${commentSafe(r.comment.split("\n")[0])}` : ""} *)`];
    if (r.comment) for (const extra of r.comment.split("\n").slice(1)) head.push(`(* ${commentSafe(extra)} *)`);
    const code = genRung(r, base, jumpFlags, zoneFlags);
    if (!code.length) code.push("(* no effect *)");
    const g = guards[idx];
    if (!g.length) return [...head, ...code];
    return [...head, `IF NOT (${g.join(" OR ")}) THEN`, ...indent(code), "END_IF;"];
  }

  // ---------------------------------------------------------------- assemble
  const prog = sanitizeIdentifier(opts.programName ?? "LogicLens");
  if (sawUnknown) {
    warnings.unshift("Unread operands (?) are translated as FALSE / 0 / T#0ms; fill them in before using this code");
  }
  const header = [
    "(* LogicLens Structured Text - IEC 61131-3 *)",
    ...(opts.generatedAt ? [`(* Generated ${commentSafe(opts.generatedAt)} *)`] : []),
    `(* ${rungs.length} rung(s). ADVISORY: verify on the target platform before use. *)`,
    ...(sawUnknown ? ["(* WARNING: unread operands (?) were translated as FALSE / 0 / T#0ms. Fill them in first. *)"] : []),
  ];
  const width = Math.max(4, ...decls.map((d) => d.name.length));
  const varLines = decls.map((d) => `  ${d.name.padEnd(width)} : ${d.type}; (* ${commentSafe(d.note)} *)`);
  const code = [...header, `PROGRAM ${prog}`, "VAR", ...varLines, "END_VAR", "", ...body, "END_PROGRAM", ""].join("\n");
  const identifiers: Record<string, string> = {};
  for (const [kk, v] of ident) identifiers[kk] = v;
  const instanceTypes: Record<string, string> = {};
  for (const [kk, v] of fbType) instanceTypes[ident.get(kk)!] = v;
  return { code, identifiers, instanceTypes, warnings: [...new Set(warnings)] };
}

