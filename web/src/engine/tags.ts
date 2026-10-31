// Tag helpers: case-insensitive keys, timer/counter member access, physical I/O
// classification from addressing conventions, and name hints used by heuristics.

import { iterInstructions } from "./parse";
import type { Instr, Mnemonic, Rung } from "./types";

/** Case-insensitive identity of a tag (Logix and most IEC tools ignore case). */
export function tagKey(raw: string): string {
  return raw.toUpperCase();
}

/** Remembers the first spelling of every tag for display. */
export class TagTable {
  private readonly names = new Map<string, string>();

  see(raw: string): string {
    const key = tagKey(raw);
    if (!this.names.has(key)) this.names.set(key, raw);
    return key;
  }

  display(key: string): string {
    return this.names.get(key) ?? key;
  }

  keys(): string[] {
    return [...this.names.keys()];
  }
}

export type Member = "DN" | "TT" | "EN" | "ACC" | "PRE" | "CU" | "CD" | "OV" | "UN";

const MEMBER_MAP: Record<string, Member> = {
  DN: "DN", TT: "TT", EN: "EN", ACC: "ACC", PRE: "PRE", CU: "CU", CD: "CD", OV: "OV", UN: "UN",
  // IEC 61131-3 names mapped onto Logix members
  Q: "DN", ET: "ACC", CV: "ACC", PV: "PRE", IN: "EN",
};

const MEMBER_RE = /^(.+)([./])([A-Za-z]+)$/;

/** `T1.DN`, `T4:0/DN`, `Tmr.Q` -> base + Logix member; null when it is not a member access. */
export function splitMember(raw: string): { base: string; member: Member } | null {
  if (raw.startsWith('"')) return null;
  const m = MEMBER_RE.exec(raw);
  if (!m) return null;
  const member = MEMBER_MAP[m[3].toUpperCase()];
  if (!member || m[1].endsWith(":")) return null;
  return { base: m[1], member };
}

export type Physical = "input" | "output" | "internal" | "unknown";

/** Physical I/O class from the addressing convention alone. */
export function physicalClass(raw: string, platform?: string): Physical {
  if (raw.startsWith('"')) return "unknown";
  if (/^I:\d/i.test(raw) || /^%I/i.test(raw) || /^[A-Za-z0-9_]+:\d+:I\./i.test(raw)) return "input";
  if (/^O:\d/i.test(raw) || /^%Q/i.test(raw) || /^[A-Za-z0-9_]+:\d+:O\./i.test(raw)) return "output";
  if (/^[BNFL]\d*:\d/i.test(raw) || /^%M/i.test(raw)) return "internal";
  if (platform === "mitsubishi") {
    if (/^X[0-9A-F]+$/i.test(raw)) return "input";
    if (/^Y[0-9A-F]+$/i.test(raw)) return "output";
    if (/^M\d+$/i.test(raw)) return "internal";
  }
  return "unknown";
}

/** Upper-case words of a tag name, split on separators and camelCase boundaries. */
export function tagWords(raw: string): string[] {
  const spaced = raw
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  return spaced
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((w) => w.toUpperCase());
}

export type NameHint =
  | "estop"
  | "stop"
  | "start"
  | "pushbutton"
  | "actuator"
  | "indicator"
  | "permissive"
  | "internal";

const ESTOP_WORD = /^(ESTOP|ESD|EMSTOP|EMGSTOP|EMERGSTOP|EMERGENCYSTOP)(\d+|PB)?$/;
const EMERGENCY_WORD = /^(E|EM|EMG|EMERG|EMERGENCY)$/;
const STOP_WORD = /^(STOP|STP|HALT)(\d+|PB)?$/;
const START_WORD = /^(START|STRT)(\d+|PB|BTN)?$/;
const PB_WORD = /^(PB|BTN|BUTTON|PUSHBUTTON)\d*$/;
const ACTUATOR_WORD =
  /^(MOTOR|MTR|PUMP|PMP|VALVE|VLV|HEATER|HTR|FAN|CONV|CONVEYOR|COMPRESSOR|BURNER|DRIVE|SOL|SOLENOID|CONTACTOR|CYL|CYLINDER|AGITATOR|MIXER)\d*$/;
const INDICATOR_WORD = /^(LAMP|LIGHT|LT|HORN|BEACON|BUZZER|IND|PILOT|SIREN)\d*$/;
const PERMISSIVE_WORD =
  /^(OL|OVERLOAD|OVLD|TRIP|TRIPPED|FAULT|FLT|LIMIT|LMT|LS|INTERLOCK|ILK|PERMISSIVE|PERM|SAFE|SAFETY|GUARD|LOW|HIGH|LO|HI|LL|HH|ALARM|ALM|READY|RDY|OK|HEALTHY)\d*$/;
const INTERNAL_WORD = /^(AUX|FLAG|FLG|MEM|TMP|STEP|STATE|LATCH|BIT|INT|SEQ|ONESHOT|OS)\d*$/;

/** Heuristic roles suggested by a tag's name (never by its address). */
export function nameHints(raw: string): NameHint[] {
  const words = tagWords(raw);
  const hints = new Set<NameHint>();
  words.forEach((w, i) => {
    const next = words[i + 1] ?? "";
    if (ESTOP_WORD.test(w) || (EMERGENCY_WORD.test(w) && next.startsWith("STOP")) || w === "EMERGENCY" || w === "EMERG") {
      hints.add("estop");
    }
    if (STOP_WORD.test(w)) hints.add("stop");
    if (START_WORD.test(w) || ((w === "ON" || w === "RUN") && PB_WORD.test(next))) hints.add("start");
    if (PB_WORD.test(w)) hints.add("pushbutton");
    if (ACTUATOR_WORD.test(w)) hints.add("actuator");
    if (INDICATOR_WORD.test(w)) hints.add("indicator");
    if (PERMISSIVE_WORD.test(w)) hints.add("permissive");
    if (INTERNAL_WORD.test(w)) hints.add("internal");
  });
  if (hints.has("estop")) hints.add("stop");
  return [...hints];
}

export const TIMER_MNEMONICS: ReadonlySet<Mnemonic> = new Set<Mnemonic>(["TON", "TOF", "RTO", "TP"]);
export const COUNTER_MNEMONICS: ReadonlySet<Mnemonic> = new Set<Mnemonic>(["CTU", "CTD", "CTUD"]);

export interface Instance {
  key: string;
  display: string;
  kind: "timer" | "counter";
  /** Distinct timer/counter mnemonics naming this instance, in order of appearance. */
  mnemonics: Mnemonic[];
  /** Every timer/counter instruction that names this instance. */
  instrIds: string[];
  /** RES instructions targeting it. */
  resets: string[];
}

/** Timers and counters of a program, keyed by tagKey of the instance tag. */
export function findInstances(rungs: Rung[]): Map<string, Instance> {
  const out = new Map<string, Instance>();
  const resets: Instr[] = [];
  for (const rung of rungs) {
    for (const ins of iterInstructions(rung.body)) {
      const op = ins.operands[0];
      if (!op || op.type !== "tag") continue;
      if (TIMER_MNEMONICS.has(ins.mnemonic) || COUNTER_MNEMONICS.has(ins.mnemonic)) {
        const key = tagKey(op.raw);
        const kind = TIMER_MNEMONICS.has(ins.mnemonic) ? "timer" : "counter";
        const cur = out.get(key) ?? { key, display: op.raw, kind, mnemonics: [], instrIds: [], resets: [] };
        if (!cur.mnemonics.includes(ins.mnemonic)) cur.mnemonics.push(ins.mnemonic);
        cur.instrIds.push(ins.id);
        out.set(key, cur);
      } else if (ins.mnemonic === "RES") {
        resets.push(ins);
      }
    }
  }
  for (const r of resets) {
    const inst = out.get(tagKey(r.operands[0].raw));
    if (inst) inst.resets.push(r.id);
  }
  return out;
}
