// Satisfiability / tautology of rung conditions.
//
// Atoms (bit reads, compares, edges) are treated as independent boolean variables and
// enumerated (<= maxVars). Compares of one tag against numeric constants are linked by
// interval reasoning over the reals, so `GRT(L,80) AND LES(L,50)` is unsatisfiable while
// integer-only contradictions such as `GRT(L,1) AND LES(L,2)` are (conservatively) not.

import { tagKey } from "./tags";
import type { Atom, Expr } from "./xref";

export interface ExprAnalysis {
  /** null when undecided (too many variables). */
  satisfiable: boolean | null;
  tautology: boolean | null;
  atoms: number;
}

type Rel = "GT" | "GE" | "LT" | "LE" | "EQ" | "NE";

interface Linear {
  idx: number;
  tag: string;
  whenTrue: [Rel, number][];
  whenFalse: [Rel, number][];
}

const NEGATE: Record<Rel, Rel> = { GT: "LE", GE: "LT", LT: "GE", LE: "GT", EQ: "NE", NE: "EQ" };
const FLIP: Record<Rel, Rel> = { GT: "LT", GE: "LE", LT: "GT", LE: "GE", EQ: "EQ", NE: "NE" };
const REL_OF: Record<string, Rel> = { GRT: "GT", GEQ: "GE", LES: "LT", LEQ: "LE", EQU: "EQ", NEQ: "NE" };

function collect(e: Expr, out: Map<string, Atom>): void {
  switch (e.op) {
    case "var":
    case "cmp":
    case "edge":
      if (!out.has(e.key)) out.set(e.key, e);
      break;
    case "not":
      collect(e.arg, out);
      break;
    case "and":
    case "or":
      for (const a of e.args) collect(a, out);
      break;
    default:
      break;
  }
}

export function atomsOf(e: Expr): Atom[] {
  const m = new Map<string, Atom>();
  collect(e, m);
  return [...m.values()];
}

function compile(e: Expr, index: Map<string, number>): (mask: number) => boolean {
  switch (e.op) {
    case "const": {
      const v = e.value;
      return () => v;
    }
    case "var":
    case "cmp":
    case "edge": {
      const bit = 1 << index.get(e.key)!;
      return (m) => (m & bit) !== 0;
    }
    case "not": {
      const f = compile(e.arg, index);
      return (m) => !f(m);
    }
    case "and": {
      const fs = e.args.map((a) => compile(a, index));
      return (m) => fs.every((f) => f(m));
    }
    case "or": {
      const fs = e.args.map((a) => compile(a, index));
      return (m) => fs.some((f) => f(m));
    }
  }
}

function linearOf(atom: Atom, idx: number): Linear | null {
  if (atom.op !== "cmp") return null;
  const ops = atom.operands;
  const num = (k: number) => (ops[k].type === "number" || ops[k].type === "time" ? (ops[k].value ?? null) : null);
  if (atom.mnemonic === "LIM") {
    const lo = num(0);
    const hi = num(2);
    if (lo === null || hi === null || lo > hi || ops[1].type !== "tag") return null;
    return { idx, tag: tagKey(ops[1].raw), whenTrue: [["GE", lo], ["LE", hi]], whenFalse: [] };
  }
  const rel = REL_OF[atom.mnemonic];
  if (ops[0].type === "tag" && num(1) !== null) {
    return { idx, tag: tagKey(ops[0].raw), whenTrue: [[rel, num(1)!]], whenFalse: [[NEGATE[rel], num(1)!]] };
  }
  if (ops[1].type === "tag" && num(0) !== null) {
    const r = FLIP[rel];
    return { idx, tag: tagKey(ops[1].raw), whenTrue: [[r, num(0)!]], whenFalse: [[NEGATE[r], num(0)!]] };
  }
  return null;
}

/** True when the relations can hold together for one real value. */
export function feasible(rels: [Rel, number][]): boolean {
  let lo = -Infinity;
  let loStrict = false;
  let hi = Infinity;
  let hiStrict = false;
  const eq: number[] = [];
  const ne: number[] = [];
  for (const [r, c] of rels) {
    switch (r) {
      case "GT":
        if (c > lo || (c === lo && !loStrict)) [lo, loStrict] = [c, true];
        break;
      case "GE":
        if (c > lo) [lo, loStrict] = [c, false];
        break;
      case "LT":
        if (c < hi || (c === hi && !hiStrict)) [hi, hiStrict] = [c, true];
        break;
      case "LE":
        if (c < hi) [hi, hiStrict] = [c, false];
        break;
      case "EQ":
        eq.push(c);
        break;
      case "NE":
        ne.push(c);
        break;
    }
  }
  if (lo > hi || (lo === hi && (loStrict || hiStrict))) return false;
  if (eq.length) {
    const v = eq[0];
    if (eq.some((x) => x !== v)) return false;
    if (v < lo || (v === lo && loStrict) || v > hi || (v === hi && hiStrict)) return false;
    return !ne.includes(v);
  }
  if (lo === hi) return !ne.includes(lo);
  return true;
}

/** Decide satisfiability and tautology of a condition. */
export function analyzeExpr(e: Expr, maxVars = 16): ExprAnalysis {
  if (e.op === "const") return { satisfiable: e.value, tautology: e.value, atoms: 0 };
  const atoms = atomsOf(e);
  if (atoms.length > maxVars) return { satisfiable: null, tautology: null, atoms: atoms.length };
  const index = new Map(atoms.map((a, i) => [a.key, i]));
  const f = compile(e, index);
  const groups = new Map<string, Linear[]>();
  atoms.forEach((a, i) => {
    const lin = linearOf(a, i);
    if (lin) groups.set(lin.tag, [...(groups.get(lin.tag) ?? []), lin]);
  });
  const linked = [...groups.values()].filter((g) => g.length > 1 || g.some((l) => l.whenTrue.length > 1));
  let anyTrue = false;
  let anyFalse = false;
  const total = 1 << atoms.length;
  for (let mask = 0; mask < total && !(anyTrue && anyFalse); mask++) {
    let ok = true;
    for (const g of linked) {
      const rels: [Rel, number][] = [];
      for (const l of g) rels.push(...((mask >> l.idx) & 1 ? l.whenTrue : l.whenFalse));
      if (!feasible(rels)) {
        ok = false;
        break;
      }
    }
    if (!ok) continue;
    if (f(mask)) anyTrue = true;
    else anyFalse = true;
  }
  return { satisfiable: anyTrue, tautology: !anyFalse, atoms: atoms.length };
}
