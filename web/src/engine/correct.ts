// Suggested corrections for findings.
//
// Only structural fixes are offered as code: merging duplicate coils, adding a seal-in,
// repairing an empty-leg "seal-in", removing redundant contacts, and (never automatically)
// swapping XIO->XIC on stops or inserting reset templates with `?` operands. Everything else,
// including every emergency-stop finding, stays advisory: no patch pretends to be a safety fix.

import type { FaultReport, Finding, RuleId } from "./faults";
import { iterInstructions, parseProgram, printSeq, roleOf } from "./parse";
import { tagKey } from "./tags";
import type { Branch, Instr, ParseResult, Rung, Seq } from "./types";

export type EditOp =
  | { op: "replace"; rungIndex: number; body: string }
  | { op: "delete"; rungIndex: number }
  | { op: "insertAfter"; rungIndex: number; body: string; comment: string };

export interface Patch {
  id: string;
  findingId: string;
  rule: RuleId;
  description: string;
  /** Canonical text of the rungs before the change (original order). */
  before: string[];
  /** Canonical text after the change; a deleted rung is absent. */
  after: string[];
  rungs: number[];
  autoApplicable: boolean;
  verification: string[];
  ops: EditOp[];
}

export interface Advisory {
  findingId: string;
  rule: RuleId;
  note: string;
}

export interface Corrections {
  patches: Patch[];
  advisories: Advisory[];
}

export interface Applied {
  text: string;
  parse: ParseResult;
}

const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;
const instr = (mnemonic: Instr["mnemonic"], raw: string): Instr => ({
  kind: "instr",
  id: "",
  mnemonic,
  operands: [{ raw, type: "tag" }],
  index: 0,
  col: 0,
});
const seqOf = (...items: (Instr | Branch)[]): Seq => ({ kind: "seq", items });

function hasOutput(seq: Seq): boolean {
  return [...iterInstructions(seq)].some((i) => roleOf(i.mnemonic) === "out");
}

/** Input part and single trailing output of a simple rung: `<inputs> OUT(...)`. */
function simpleShape(rung: Rung): { inputs: Seq; out: Instr } | null {
  const items = rung.body.items;
  const last = items[items.length - 1];
  if (!last || last.kind !== "instr" || roleOf(last.mnemonic) !== "out") return null;
  const inputs = seqOf(...items.slice(0, -1));
  return hasOutput(inputs) ? null : { inputs, out: last };
}

/** Remove series contacts already required earlier on the same path, and duplicate legs. */
function dedupe(seq: Seq, ctx: Set<string>): Seq {
  const local = new Set(ctx);
  const items: (Instr | Branch)[] = [];
  for (const item of seq.items) {
    if (item.kind === "instr") {
      if (item.mnemonic === "XIC" || item.mnemonic === "XIO") {
        const lit = `${item.mnemonic === "XIC" ? "+" : "-"}${tagKey(item.operands[0].raw)}`;
        if (local.has(lit)) continue;
        local.add(lit);
      }
      items.push(item);
      continue;
    }
    const seen = new Set<string>();
    const legs: Seq[] = [];
    for (const leg of item.legs) {
      const d = dedupe(leg, local);
      const key = printSeq(d);
      if (key !== "" && seen.has(key)) continue;
      seen.add(key);
      legs.push(d);
    }
    if (legs.length === 1) items.push(...legs[0].items);
    else items.push({ kind: "branch", legs });
  }
  return { kind: "seq", items };
}

export function suggestCorrections(rungs: Rung[], faults: FaultReport | Finding[]): Corrections {
  const findings = Array.isArray(faults) ? faults : faults.findings;
  const patches: Patch[] = [];
  const advisories: Advisory[] = [];
  const touched = new Map<number, string>();
  const indexOfRung = (instrId: string) => Number(/^r(\d+)i/.exec(instrId)?.[1] ?? -1);
  const rungText = (i: number) => rungs[i].text;

  const addPatch = (f: Finding, p: Omit<Patch, "id" | "findingId" | "rule" | "before" | "after" | "rungs">) => {
    const idxs = [...new Set(p.ops.map((o) => o.rungIndex))].sort((a, b) => a - b);
    const conflict = idxs.find((i) => touched.has(i));
    const autoApplicable = p.autoApplicable && conflict === undefined;
    const verification = conflict === undefined ? p.verification : [...p.verification, `Overlaps ${touched.get(conflict)} on rung ${rungs[conflict].number}: apply one, re-run the analysis, then apply the other.`];
    const id = `P${patches.length + 1}`;
    if (autoApplicable) for (const i of idxs) touched.set(i, id);
    const preview = applyOps(rungs, p.ops);
    patches.push({
      id,
      findingId: f.id,
      rule: f.rule,
      description: p.description,
      before: idxs.map(rungText),
      after: preview.changed,
      rungs: idxs.map((i) => rungs[i].number),
      autoApplicable,
      verification,
      ops: p.ops,
    });
  };

  for (const f of findings) {
    const idxs = [...new Set(f.instrIds.map(indexOfRung))].filter((i) => i >= 0);
    switch (f.rule) {
      case "DUPLICATE_OUTPUT": {
        const target = f.tags[0];
        const shapes = idxs.map((i) => ({ i, s: simpleShape(rungs[i]) }));
        const ok = shapes.every(({ s }) => s && s.out.mnemonic === "OTE" && tagKey(s.out.operands[0].raw) === tagKey(target));
        if (!ok || idxs.length < 2) {
          advisories.push({ findingId: f.id, rule: f.rule, note: `${f.recommendation} (rung shapes are too complex to merge automatically)` });
          break;
        }
        const legs = shapes.map(({ s }) => printSeq(s!.inputs));
        const merged = `[${legs.join(",")}]OTE(${target})`;
        const last = idxs[idxs.length - 1];
        addPatch(f, {
          description: `Merge the ${idxs.length} coils of ${target} into rung ${rungs[last].number} as parallel branches (OR of the conditions) and delete the others.`,
          autoApplicable: true,
          verification: [
            `${target} energizes when any of the original rung conditions is true.`,
            `No other logic relied on the old last-rung-wins behaviour (a one-scan pulse of ${target}).`,
          ],
          ops: [...idxs.slice(0, -1).map((i) => ({ op: "delete" as const, rungIndex: i })), { op: "replace", rungIndex: last, body: merged }],
        });
        break;
      }
      case "MISSING_SEAL_IN": {
        const i = idxs[0];
        const [out, start] = f.tags;
        const items = rungs[i].body.items;
        const k = items.findIndex((it) => it.kind === "instr" && it.mnemonic === "XIC" && tagKey(it.operands[0].raw) === tagKey(start));
        if (k < 0) {
          advisories.push({ findingId: f.id, rule: f.rule, note: f.recommendation });
          break;
        }
        const body = clone(rungs[i].body);
        body.items[k] = { kind: "branch", legs: [seqOf(instr("XIC", start)), seqOf(instr("XIC", out))] };
        addPatch(f, {
          description: `Add a seal-in: put XIC(${out}) in parallel with ${start}.`,
          autoApplicable: true,
          verification: [`${start} is a momentary push-button (not a maintained switch).`, `${out} stays on after ${start} is released and drops out on every stop/trip condition.`],
          ops: [{ op: "replace", rungIndex: i, body: printSeq(body) }],
        });
        break;
      }
      case "BRANCH_BYPASSED": {
        const i = idxs[0];
        const shape = simpleShape(rungs[i]);
        const items = rungs[i].body.items;
        const k = items.findIndex(
          (it, n) =>
            it.kind === "branch" &&
            it.legs.length === 2 &&
            it.legs.some((l) => l.items.length === 0) &&
            n > 0 &&
            items[n - 1].kind === "instr" &&
            (items[n - 1] as Instr).mnemonic === "XIC",
        );
        const br = k >= 0 ? (items[k] as Branch) : null;
        const leg = br?.legs.find((l) => l.items.length > 0);
        const only = leg && leg.items.length === 1 && leg.items[0].kind === "instr" ? (leg.items[0] as Instr) : null;
        if (!shape || !br || !only || only.mnemonic !== "XIC" || tagKey(only.operands[0].raw) !== tagKey(shape.out.operands[0]?.raw ?? "")) {
          advisories.push({ findingId: f.id, rule: f.rule, note: f.recommendation });
          break;
        }
        const start = items[k - 1] as Instr;
        const body = clone(rungs[i].body);
        body.items.splice(k - 1, 2, { kind: "branch", legs: [seqOf(clone(start)), seqOf(clone(only))] });
        addPatch(f, {
          description: `Repair the seal-in: put ${only.operands[0].raw} in parallel with ${start.operands[0].raw} instead of next to an empty leg.`,
          autoApplicable: true,
          verification: [`${only.operands[0].raw} latches on after ${start.operands[0].raw} is released and drops out on stop.`],
          ops: [{ op: "replace", rungIndex: i, body: printSeq(body) }],
        });
        break;
      }
      case "REDUNDANT_CONTACT": {
        const i = idxs[0] ?? rungs.findIndex((r) => r.number === f.rungs[0]);
        if (i < 0) break;
        const rung = rungs[i];
        const outsBeforeLastInput = (() => {
          let seenOut = false;
          for (const ins of iterInstructions(rung.body)) {
            if (roleOf(ins.mnemonic) === "out") seenOut = true;
            else if (seenOut) return true;
          }
          return false;
        })();
        const body = dedupe(rung.body, new Set());
        if (outsBeforeLastInput || printSeq(body) === printSeq(rung.body)) {
          advisories.push({ findingId: f.id, rule: f.rule, note: f.recommendation });
          break;
        }
        addPatch(f, {
          description: `Remove the redundant contact(s)/leg(s) from rung ${rung.number}.`,
          autoApplicable: true,
          verification: ["The rung energizes under exactly the same conditions as before."],
          ops: [{ op: "replace", rungIndex: i, body: printSeq(body) }],
        });
        break;
      }
      case "STOP_EXAMINED_WITH_XIO": {
        const tag = f.tags[0];
        const ops: EditOp[] = idxs.map((i) => {
          const body = clone(rungs[i].body);
          const swap = (s: Seq) => {
            for (const it of s.items) {
              if (it.kind === "instr" && it.mnemonic === "XIO" && tagKey(it.operands[0].raw) === tagKey(tag)) it.mnemonic = "XIC";
              else if (it.kind === "branch") it.legs.forEach(swap);
            }
          };
          swap(body);
          return { op: "replace", rungIndex: i, body: printSeq(body) };
        });
        addPatch(f, {
          description: `Examine ${tag} with XIC (only correct once the device is wired normally-closed).`,
          autoApplicable: false,
          verification: [`${tag} is wired NC in the field (bit = 1 when healthy).`, `Pressing ${tag} or breaking its wire stops the equipment.`],
          ops,
        });
        break;
      }
      case "LATCH_WITHOUT_UNLATCH":
      case "COUNTER_NO_RESET":
      case "RTO_NO_RESET": {
        const tag = f.tags[0];
        const last = Math.max(...idxs);
        const latch = f.rule === "LATCH_WITHOUT_UNLATCH";
        addPatch(f, {
          description: latch
            ? `Insert an unlatch rung for ${tag}; replace ? with the reset/acknowledge condition.`
            : `Insert a reset rung for ${tag}; replace ? with the condition that starts a new cycle.`,
          autoApplicable: false,
          verification: ["Fill in the ? operand before applying.", latch ? `${tag} clears when the reset condition is true.` : `${tag} returns to 0 at the start of every cycle.`],
          ops: [
            {
              op: "insertAfter",
              rungIndex: last,
              body: latch ? `XIC(?)OTU(${tag})` : `XIC(?)RES(${tag})`,
              comment: latch ? `Reset ${tag} (added by LogicLens: fill in the condition)` : `Reset ${tag} (added by LogicLens: fill in the condition)`,
            },
          ],
        });
        break;
      }
      case "ESTOP_IN_STANDARD_LOGIC":
        advisories.push({
          findingId: f.id,
          rule: f.rule,
          note: "No code change is offered: an emergency stop is fixed in the safety-rated hardware/safety program, not by editing standard ladder logic.",
        });
        break;
      default:
        advisories.push({ findingId: f.id, rule: f.rule, note: f.recommendation });
    }
  }
  return { patches, advisories };
}

interface Draft {
  body: string;
  comment: string | null;
  from: number | null;
}

function applyOps(rungs: Rung[], ops: EditOp[]): { drafts: Draft[]; changed: string[] } {
  const drafts: (Draft | null)[] = rungs.map((r, i) => ({ body: r.text.replace(/;$/, ""), comment: r.comment, from: i }));
  const inserts = new Map<number, Draft[]>();
  const changed: string[] = [];
  for (const o of ops) {
    if (o.op === "replace" && drafts[o.rungIndex]) {
      drafts[o.rungIndex] = { ...drafts[o.rungIndex]!, body: o.body };
      changed.push(`${o.body};`);
    } else if (o.op === "delete") drafts[o.rungIndex] = null;
    else if (o.op === "insertAfter") {
      inserts.set(o.rungIndex, [...(inserts.get(o.rungIndex) ?? []), { body: o.body, comment: o.comment, from: null }]);
      changed.push(`${o.body};`);
    }
  }
  const out: Draft[] = [];
  drafts.forEach((d, i) => {
    if (d) out.push(d);
    out.push(...(inserts.get(i) ?? []));
  });
  return { drafts: out, changed };
}

/** Apply patches (normally the auto-applicable ones) and re-parse the result. */
export function applyPatches(rungs: Rung[], patches: Patch[]): Applied {
  const { drafts } = applyOps(rungs, patches.flatMap((p) => p.ops));
  const lines: string[] = [];
  for (const d of drafts) {
    if (d.comment) for (const c of d.comment.split("\n")) lines.push(`// ${c}`);
    lines.push(`${d.body};`);
  }
  const text = lines.join("\n");
  return { text, parse: parseProgram(text) };
}
