// Data types of tags, inferred from how the program uses them. LLT carries no declarations,
// so the simulator and the Structured Text generator share this one inference to agree on
// BOOL / DINT / REAL semantics (DINT writes truncate toward zero and wrap to 32 bits).

import { iterInstructions } from "./parse";
import { findInstances, splitMember, tagKey, type Instance } from "./tags";
import type { Instr, Rung } from "./types";

export type DataType = "BOOL" | "DINT" | "REAL";

const BIT_OPS = new Set(["XIC", "XIO", "P", "N", "OTE", "OTL", "OTU", "NCOIL", "ONS"]);
const BITWISE = new Set(["AND", "OR", "XOR", "NOT"]);
const NUMERIC = new Set(["EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ", "LIM", "ADD", "SUB", "MUL", "DIV", "MOV", "AND", "OR", "XOR", "NOT"]);

/** Usage of operand k of an instruction: "bit", "num", "int" (bitwise), or null (instance/label). */
export function operandUsage(ins: Instr, k: number): "bit" | "num" | "int" | null {
  const m = ins.mnemonic;
  if (BIT_OPS.has(m)) return "bit";
  if (m === "OSR" || m === "OSF") return "bit";
  if (BITWISE.has(m)) return "int";
  if (NUMERIC.has(m)) return "num";
  if (["TON", "TOF", "RTO", "TP", "CTU", "CTD"].includes(m)) return k === 0 ? null : "num";
  if (m === "CTUD") return k === 0 ? null : k === 2 ? "bit" : "num";
  return null; // RES, JMP, LBL, JSR, MCR, END, NOP, AFI
}

/** True when a member access refers to a timer/counter instance of this program. */
export function isInstanceMember(raw: string, instances: Map<string, Instance>): boolean {
  const m = splitMember(raw);
  return !!m && instances.has(tagKey(m.base));
}

export function inferTypes(rungs: Rung[], instances: Map<string, Instance> = findInstances(rungs)): Map<string, DataType> {
  const usage = new Map<string, { bit: boolean; num: boolean; int: boolean; raw: string }>();
  for (const rung of rungs) {
    for (const ins of iterInstructions(rung.body)) {
      ins.operands.forEach((o, k) => {
        if (o.type !== "tag") return;
        const u = operandUsage(ins, k);
        if (!u) return;
        if (isInstanceMember(o.raw, instances) || instances.has(tagKey(o.raw))) return;
        const key = tagKey(o.raw);
        const cur = usage.get(key) ?? { bit: false, num: false, int: false, raw: o.raw };
        if (u === "bit") cur.bit = true;
        else if (u === "num") cur.num = true;
        else {
          cur.num = true;
          cur.int = true;
        }
        usage.set(key, cur);
      });
    }
  }
  const out = new Map<string, DataType>();
  for (const [key, u] of usage) {
    if (!u.num) {
      out.set(key, "BOOL");
      continue;
    }
    if (u.int || /^N\d+:/i.test(u.raw) || /^%[MIQ][WD]/i.test(u.raw)) out.set(key, "DINT");
    else out.set(key, "REAL");
  }
  return out;
}

/** IEC/Logix DINT store: truncate toward zero and wrap to 32 bits; non-finite -> 0. */
export function toDint(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.trunc(v) | 0;
}

export function coerce(type: DataType | undefined, v: number | boolean): number | boolean {
  if (type === "BOOL") return typeof v === "boolean" ? v : v !== 0;
  const n = typeof v === "boolean" ? (v ? 1 : 0) : v;
  return type === "DINT" ? toDint(n) : n;
}
