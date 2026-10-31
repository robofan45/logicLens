// Scan-cycle simulator with Logix rung-condition semantics (contract §1.4).
//
// Rungs run top to bottom; writes are visible to later rungs in the same scan. Timers use
// "the enabling scan contributes 0 ms, every following scan adds dt" so a TON with PRE = 3 * dt
// is done on the 4th enabled scan. The Structured Text generator targets the same semantics.

import { coerce, inferTypes, toDint, type DataType } from "./datatypes";
import { classifyOperand, iterInstructions, roleOf, timerPresetMs } from "./parse";
import { findInstances, splitMember, TagTable, tagKey, type Member } from "./tags";
import type { Instr, Mnemonic, Operand, Rung, Seq } from "./types";
import { buildXref, operandAccess } from "./xref";

export interface TimerState {
  kind: Mnemonic;
  PRE: number;
  ACC: number;
  EN: boolean;
  TT: boolean;
  DN: boolean;
}

export interface CounterState {
  kind: Mnemonic;
  PRE: number;
  ACC: number;
  CU: boolean;
  CD: boolean;
  DN: boolean;
  OV: boolean;
  UN: boolean;
}

export interface InstrPower {
  in: boolean;
  out: boolean;
}

export interface ScanResult {
  scan: number;
  /** Display names of tags (and timer/counter instances) whose value changed. */
  changed: string[];
  /** Rung-condition in/out of every instruction executed in this scan, by instruction id. */
  power: Record<string, InstrPower>;
  /** Rung numbers that executed (jumped-over rungs are missing). */
  executedRungs: number[];
  warnings: string[];
  /** Set when the scan aborted (watchdog). */
  fault: string | null;
}

export type Value = boolean | number;

export interface Simulator {
  /** Tags the program never writes: the ones a user sets. */
  readonly inputs: string[];
  /** Every plain tag (not timer/counter instances or their members). */
  readonly tags: string[];
  readonly types: ReadonlyMap<string, DataType>;
  readonly scanCount: number;
  setInput(tag: string, value: Value): void;
  /** Force a tag (reads return it, program writes are ignored); null removes the force. */
  force(tag: string, value: Value | null): void;
  forced(): Record<string, Value>;
  scan(dtMs: number): ScanResult;
  /** Current value of a tag or member (`T1.DN`, `T4:0/ACC`). */
  read(tag: string): Value;
  readBit(tag: string): boolean;
  snapshot(): Record<string, Value>;
  timer(tag: string): TimerState | undefined;
  counter(tag: string): CounterState | undefined;
  reset(): void;
}

export interface SimulatorOptions {
  /** Watchdog: instruction executions allowed per scan (default 100 000). */
  maxExecutionsPerScan?: number;
}

/** True for operands that are literals (numbers, times, `?`), which can never be written. */
const classifyLiteral = (raw: string): boolean => classifyOperand(raw)?.type !== "tag";

const asBit = (v: Value | undefined): boolean => (typeof v === "boolean" ? v : (v ?? 0) !== 0);
const asNum = (v: Value | undefined): number => (typeof v === "number" ? v : v ? 1 : 0);

function timerMember(t: TimerState, m: Member): Value {
  switch (m) {
    case "DN":
      return t.DN;
    case "TT":
      return t.TT;
    case "EN":
      return t.EN;
    case "ACC":
      return t.ACC;
    case "PRE":
      return t.PRE;
    default:
      return false;
  }
}

function counterMember(c: CounterState, m: Member): Value {
  switch (m) {
    case "DN":
      return c.DN;
    case "CU":
      return c.CU;
    case "CD":
      return c.CD;
    case "OV":
      return c.OV;
    case "UN":
      return c.UN;
    case "ACC":
      return c.ACC;
    case "PRE":
      return c.PRE;
    default:
      return false;
  }
}

export function createSimulator(rungs: Rung[], opts: SimulatorOptions = {}): Simulator {
  const maxExec = opts.maxExecutionsPerScan ?? 100_000;
  const instances = findInstances(rungs);
  const types = inferTypes(rungs, instances);
  const xref = buildXref(rungs);
  const table = new TagTable();
  const written = new Set<string>();
  const labelRung = new Map<string, number>();
  const unconditionalMcr = new Set<string>();

  rungs.forEach((rung, idx) => {
    for (const ins of iterInstructions(rung.body)) {
      ins.operands.forEach((o, k) => {
        const a = operandAccess(ins, k);
        if (a === "label") {
          if (ins.mnemonic === "LBL" && !labelRung.has(tagKey(o.raw))) labelRung.set(tagKey(o.raw), idx);
          return;
        }
        if (a === "routine" || o.type !== "tag") return;
        table.see(o.raw);
        if (a === "w" || a === "rw" || a === "inst") written.add(tagKey(o.raw));
      });
      if (ins.mnemonic === "MCR") {
        const c = xref.instructions.get(ins.id)!.conditionIn;
        if (c.op === "const" && c.value) unconditionalMcr.add(ins.id);
      }
    }
  });

  const isInstance = (key: string) => instances.has(key);
  const isInstanceMember = (raw: string) => {
    const m = splitMember(raw);
    return !!m && instances.has(tagKey(m.base));
  };
  const plainKeys = table.keys().filter((k) => !isInstance(k) && !isInstanceMember(table.display(k)));
  const inputs = plainKeys.filter((k) => !written.has(k)).map((k) => table.display(k));

  let mem = new Map<string, Value>();
  let timers = new Map<string, TimerState>();
  let counters = new Map<string, CounterState>();
  let edges = new Map<string, boolean>();
  const forces = new Map<string, Value>();
  let scanCount = 0;
  const jsrWarned = new Set<string>();

  function init(): void {
    mem = new Map();
    for (const k of plainKeys) mem.set(k, types.get(k) === "BOOL" || !types.has(k) ? false : 0);
    timers = new Map();
    counters = new Map();
    for (const inst of instances.values()) {
      if (inst.kind === "timer") timers.set(inst.key, { kind: inst.mnemonics[0], PRE: 0, ACC: 0, EN: false, TT: false, DN: false });
      else counters.set(inst.key, { kind: inst.mnemonics[0], PRE: 0, ACC: 0, CU: false, CD: false, DN: false, OV: false, UN: false });
    }
    edges = new Map();
    scanCount = 0;
  }
  init();

  function read(raw: string): Value {
    const key = tagKey(raw);
    if (forces.has(key)) return forces.get(key)!;
    const m = splitMember(raw);
    if (m) {
      const ik = tagKey(m.base);
      const t = timers.get(ik);
      if (t) return timerMember(t, m.member);
      const c = counters.get(ik);
      if (c) return counterMember(c, m.member);
    }
    return mem.get(key) ?? false;
  }

  const readBit = (raw: string) => asBit(read(raw));
  const num = (o: Operand | undefined): number => {
    if (!o) return 0;
    if (o.type === "number" || o.type === "time") return o.value ?? 0;
    if (o.type === "unknown") return 0;
    return asNum(read(o.raw));
  };

  function write(raw: string, v: Value): void {
    const key = tagKey(raw);
    if (forces.has(key) || instances.has(key) || classifyLiteral(raw)) return;
    const m = splitMember(raw);
    if (m) {
      const ik = tagKey(m.base);
      const t = timers.get(ik);
      const c = counters.get(ik);
      if (t || c) {
        const target = (t ?? c) as unknown as Record<string, Value>;
        if (m.member === "ACC" || m.member === "PRE") target[m.member] = asNum(v);
        else target[m.member] = asBit(v);
        return;
      }
    }
    mem.set(key, coerce(types.get(key), v));
  }

  function presetOf(ins: Instr): number {
    const ms = timerPresetMs(ins);
    if (ms !== null) return ms;
    const op = ins.operands.length === 4 ? ins.operands[2] : ins.operands[1];
    return op?.type === "tag" ? num(op) : 0;
  }

  function runTimer(ins: Instr, cond: boolean, dt: number): void {
    const t = timers.get(tagKey(ins.operands[0].raw))!;
    const pre = presetOf(ins);
    t.PRE = pre;
    const step = (acc: number) => (pre <= 0 ? acc : Math.min(acc + dt, pre));
    switch (ins.mnemonic) {
      case "TON":
        if (cond) {
          t.ACC = t.EN ? step(t.ACC) : 0;
          t.EN = true;
          t.DN = t.ACC >= pre;
          t.TT = !t.DN;
        } else {
          t.ACC = 0;
          t.EN = t.TT = t.DN = false;
        }
        break;
      case "TOF":
        if (cond) {
          t.EN = true;
          t.DN = true;
          t.TT = false;
          t.ACC = 0;
        } else {
          if (t.EN) t.ACC = 0;
          else if (t.DN) t.ACC = step(t.ACC);
          t.EN = false;
          if (t.DN && t.ACC >= pre) t.DN = false;
          t.TT = t.DN;
        }
        break;
      case "RTO":
        if (cond) {
          if (t.EN && t.ACC < pre) t.ACC = step(t.ACC);
          t.EN = true;
          t.DN = t.ACC >= pre;
          t.TT = !t.DN;
        } else {
          t.EN = false;
          t.TT = false;
          t.DN = t.ACC >= pre;
        }
        break;
      case "TP": {
        const rising = cond && !t.EN;
        if (t.DN) {
          t.ACC = step(t.ACC);
          if (t.ACC >= pre) t.DN = false;
        } else if (rising && t.ACC === 0) {
          t.DN = pre > 0;
          t.ACC = 0;
        }
        if (!t.DN && !cond) t.ACC = 0;
        t.EN = cond;
        t.TT = t.DN;
        break;
      }
      default:
        break;
    }
  }

  function runCounter(ins: Instr, cond: boolean): void {
    const c = counters.get(tagKey(ins.operands[0].raw))!;
    c.PRE = num(ins.operands[1]);
    if (ins.mnemonic === "CTU") {
      if (cond && !c.CU) c.ACC = toDint(c.ACC + 1);
      c.CU = cond;
    } else if (ins.mnemonic === "CTD") {
      if (cond && !c.CD) c.ACC = toDint(c.ACC - 1);
      c.CD = cond;
    } else {
      const down = bitOf(ins.operands[2]);
      const up = cond && !c.CU;
      const dn = down && !c.CD;
      if (up && !dn) c.ACC = toDint(c.ACC + 1);
      else if (dn && !up) c.ACC = toDint(c.ACC - 1);
      c.CU = cond;
      c.CD = down;
    }
    c.DN = c.ACC >= c.PRE;
  }

  function cmp(m: Mnemonic, ops: Operand[]): boolean {
    const a = num(ops[0]);
    const b = num(ops[1]);
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
      case "LIM": {
        const lo = a;
        const t = b;
        const hi = num(ops[2]);
        return lo <= hi ? lo <= t && t <= hi : t >= lo || t <= hi;
      }
      default:
        return false;
    }
  }

  // ------------------------------------------------------------------ one scan
  interface Ctx {
    dt: number;
    power: Record<string, InstrPower>;
    warnings: string[];
    exec: number;
    jump: string | null;
    end: boolean;
    zoneFalse: boolean;
  }

  class Watchdog extends Error {}

  /** Bit value of an operand: literal numbers are constants, `?` and timer instances read 0. */
  const bitOf = (o: Operand | undefined): boolean => {
    if (!o || o.type === "unknown") return false;
    if (o.type !== "tag") return (o.value ?? 0) !== 0;
    if (instances.has(tagKey(o.raw))) return false;
    return readBit(o.raw);
  };

  function exec(ins: Instr, cond: boolean, ctx: Ctx): boolean {
    if (++ctx.exec > maxExec) throw new Watchdog();
    const ops = ins.operands;
    const tag = ops[0]?.raw ?? "";
    let out = cond;
    switch (ins.mnemonic) {
      case "XIC":
        out = cond && bitOf(ops[0]);
        break;
      case "XIO":
        out = cond && !bitOf(ops[0]);
        break;
      case "ONS": {
        const prev = readBit(tag);
        out = cond && !prev;
        write(tag, cond);
        break;
      }
      case "P":
      case "N": {
        const v = bitOf(ops[0]);
        const prev = edges.get(ins.id) ?? false;
        out = cond && (ins.mnemonic === "P" ? v && !prev : !v && prev);
        edges.set(ins.id, v);
        break;
      }
      case "EQU":
      case "NEQ":
      case "GRT":
      case "GEQ":
      case "LES":
      case "LEQ":
      case "LIM":
        out = cond && cmp(ins.mnemonic, ops);
        break;
      case "AFI":
        out = false;
        break;
      case "LBL":
        break;
      case "OTE":
        write(tag, cond);
        break;
      case "NCOIL":
        write(tag, !cond);
        break;
      case "OTL":
        if (cond) write(tag, true);
        break;
      case "OTU":
        if (cond) write(tag, false);
        break;
      case "OSR":
      case "OSF": {
        const prev = readBit(tag);
        write(ops[1].raw, ins.mnemonic === "OSR" ? cond && !prev : !cond && prev);
        write(tag, cond);
        break;
      }
      case "TON":
      case "TOF":
      case "RTO":
      case "TP":
        runTimer(ins, cond, ctx.dt);
        break;
      case "CTU":
      case "CTD":
      case "CTUD":
        runCounter(ins, cond);
        break;
      case "RES":
        if (cond) {
          const k = tagKey(tag);
          const t = timers.get(k);
          if (t) Object.assign(t, { ACC: 0, EN: false, TT: false, DN: false });
          const c = counters.get(k);
          if (c) Object.assign(c, { ACC: 0, CU: false, CD: false, DN: false, OV: false, UN: false });
        }
        break;
      case "ADD":
      case "SUB":
      case "MUL":
      case "DIV": {
        if (!cond) break;
        const a = num(ops[0]);
        const b = num(ops[1]);
        let r: number;
        if (ins.mnemonic === "ADD") r = a + b;
        else if (ins.mnemonic === "SUB") r = a - b;
        else if (ins.mnemonic === "MUL") r = a * b;
        else if (b === 0) {
          r = 0;
          ctx.warnings.push(`Division by zero in ${ins.id}; destination set to 0`);
        } else r = a / b;
        write(ops[2].raw, r);
        break;
      }
      case "AND":
      case "OR":
      case "XOR": {
        if (!cond) break;
        const a = toDint(num(ops[0]));
        const b = toDint(num(ops[1]));
        write(ops[2].raw, ins.mnemonic === "AND" ? a & b : ins.mnemonic === "OR" ? a | b : a ^ b);
        break;
      }
      case "NOT":
        if (cond) write(ops[1].raw, ~toDint(num(ops[0])));
        break;
      case "MOV":
        if (cond) write(ops[1].raw, ops[0].type === "tag" ? read(ops[0].raw) : num(ops[0]));
        break;
      case "JMP":
        if (cond) ctx.jump = tagKey(tag);
        break;
      case "JSR":
        if (cond && !jsrWarned.has(tag)) {
          jsrWarned.add(tag);
          ctx.warnings.push(`JSR(${tag}) is not simulated: the subroutine is not part of this program`);
        }
        break;
      case "MCR":
        if (unconditionalMcr.has(ins.id)) ctx.zoneFalse = false;
        else ctx.zoneFalse = !cond;
        break;
      case "END":
        ctx.end = true;
        break;
      case "NOP":
        break;
    }
    ctx.power[ins.id] = { in: cond, out };
    return roleOf(ins.mnemonic) === "in" ? out : cond;
  }

  function runSeq(seq: Seq, cond: boolean, ctx: Ctx): boolean {
    let c = cond;
    for (const item of seq.items) {
      if (item.kind === "instr") c = exec(item, c, ctx);
      else {
        let any = false;
        for (const leg of item.legs) if (runSeq(leg, c, ctx)) any = true;
        c = any;
      }
    }
    return c;
  }

  function snapshotState(): Map<string, string> {
    const s = new Map<string, string>();
    for (const [k, v] of mem) s.set(table.display(k), String(v));
    for (const [k, t] of timers) s.set(table.display(k), `${t.DN}|${t.ACC}|${t.EN}`);
    for (const [k, c] of counters) s.set(table.display(k), `${c.DN}|${c.ACC}`);
    return s;
  }

  function scan(dtMs: number): ScanResult {
    const before = snapshotState();
    const ctx: Ctx = { dt: Math.max(0, dtMs), power: {}, warnings: [], exec: 0, jump: null, end: false, zoneFalse: false };
    const executed: number[] = [];
    let fault: string | null = null;
    let i = 0;
    try {
      while (i < rungs.length && !ctx.end) {
        const rung = rungs[i];
        executed.push(rung.number);
        ctx.jump = null;
        runSeq(rung.body, !ctx.zoneFalse || rungHasMcr(rung), ctx);
        if (ctx.jump !== null) {
          const target = labelRung.get(ctx.jump);
          if (target === undefined) {
            ctx.warnings.push(`JMP target ${ctx.jump} not found; jump ignored`);
            i++;
          } else i = target;
        } else i++;
      }
    } catch (e) {
      if (!(e instanceof Watchdog)) throw e;
      fault = `WATCHDOG: more than ${maxExec} instruction executions in one scan (backward jump loop?)`;
    }
    scanCount++;
    const after = snapshotState();
    const changed = [...after.keys()].filter((k) => before.get(k) !== after.get(k));
    return { scan: scanCount, changed, power: ctx.power, executedRungs: executed, warnings: ctx.warnings, fault };
  }

  const mcrRungs = new Set<Rung>(rungs.filter((r) => [...iterInstructions(r.body)].some((i) => i.mnemonic === "MCR")));
  function rungHasMcr(r: Rung): boolean {
    return mcrRungs.has(r);
  }

  return {
    inputs,
    tags: plainKeys.map((k) => table.display(k)),
    types,
    get scanCount() {
      return scanCount;
    },
    setInput(tag: string, value: Value) {
      const key = tagKey(tag);
      mem.set(key, coerce(types.get(key), value));
    },
    force(tag: string, value: Value | null) {
      const key = tagKey(tag);
      if (value === null) forces.delete(key);
      else forces.set(key, value);
    },
    forced() {
      return Object.fromEntries([...forces].map(([k, v]) => [table.display(k), v]));
    },
    scan,
    read,
    readBit,
    snapshot() {
      return Object.fromEntries(plainKeys.map((k) => [table.display(k), read(table.display(k))]));
    },
    timer: (tag: string) => {
      const t = timers.get(tagKey(tag));
      return t ? { ...t } : undefined;
    },
    counter: (tag: string) => {
      const c = counters.get(tagKey(tag));
      return c ? { ...c } : undefined;
    },
    reset() {
      init();
      jsrWarned.clear();
    },
  };
}

