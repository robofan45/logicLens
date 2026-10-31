// (c) 2000 random valid programs through the whole pipeline plus 200 simulator scans each.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { analyzeProgram, applyPatches, createSimulator, iterInstructions, tagKey } from "../../../src/engine";
import { programArb } from "../../helpers/program-arb";
import { StInterpreter } from "../../helpers/st-interpreter";

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const IDENT = /^[A-Za-z][A-Za-z0-9_]*$/;

describe("(c) fuzz: random programs never break the engine", () => {
  it("2000 programs x 200 scans hold every invariant", () => {
    let programs = 0;
    let scans = 0;
    let watchdogs = 0;
    fc.assert(
      fc.property(programArb({ maxRungs: 8 }), fc.integer({ min: 1, max: 2 ** 31 - 1 }), (text, seed) => {
        const a = analyzeProgram(text);
        expect(a.parse.errors, text).toEqual([]);
        programs++;

        // ST: balanced blocks, valid identifiers, and it parses as ST
        const lines = a.st.code.split("\n").map((l) => l.trim());
        expect(lines.filter((l) => l.startsWith("IF ")).length).toBe(lines.filter((l) => l === "END_IF;").length);
        for (const l of a.st.code.split("\n").filter((x) => /^\s{2}\S+\s+: /.test(x))) {
          const name = l.trim().split(/\s+/)[0];
          expect(name).toMatch(IDENT);
          expect(name).not.toMatch(/__|_$/);
        }
        new StInterpreter(a.st.code);

        // corrections re-parse
        const applied = applyPatches(a.parse.rungs, a.corrections.patches.filter((p) => p.autoApplicable));
        expect(applied.parse.errors, applied.text).toEqual([]);

        // simulation invariants
        const rnd = mulberry32(seed);
        const sim = createSimulator(a.parse.rungs, { maxExecutionsPerScan: 20_000 });
        const coilWriters = new Map<string, string[]>();
        const otherWrites = new Set<string>();
        for (const r of a.parse.rungs) {
          for (const ins of iterInstructions(r.body)) {
            ins.operands.forEach((o, k) => {
              if (o.type !== "tag") return;
              const key = tagKey(o.raw);
              if (ins.mnemonic === "OTE" && k === 0) coilWriters.set(key, [...(coilWriters.get(key) ?? []), ins.id]);
              else if (!["XIC", "XIO", "P", "N", "GRT", "LES", "GEQ", "LEQ", "EQU", "NEQ", "LIM"].includes(ins.mnemonic)) otherWrites.add(key);
            });
          }
        }
        const singleOte = [...coilWriters].filter(([k, ids]) => ids.length === 1 && !otherWrites.has(k));
        const tonOnly = [...a.xref.instances.values()].filter((i) => i.instrIds.length === 1 && i.mnemonics[0] === "TON");
        for (let s = 0; s < 200; s++) {
          for (const t of sim.inputs) {
            if (rnd() < 0.3) sim.setInput(t, sim.types.get(tagKey(t)) === "BOOL" || !sim.types.has(tagKey(t)) ? rnd() < 0.5 : Math.floor(rnd() * 40) - 5);
          }
          const r = sim.scan([0, 10, 50, 100, 250][Math.floor(rnd() * 5)]);
          scans++;
          if (r.fault) {
            watchdogs++;
            break;
          }
          for (const inst of tonOnly) {
            const t = sim.timer(inst.display)!;
            expect(t.ACC).toBeLessThanOrEqual(Math.max(t.PRE, 0));
          }
          for (const [key, [id]] of singleOte) {
            const p = r.power[id];
            if (p) expect(sim.readBit(a.xref.table.display(key)), `${key} in ${text}`).toBe(p.in);
          }
        }
        return true;
      }),
      { numRuns: 2000, seed: 424242 },
    );
    expect(programs).toBe(2000);
    expect(scans).toBeGreaterThan(300_000);
    console.info(`fuzz: ${programs} programs, ${scans} scans, ${watchdogs} watchdog trips (backward jumps)`);
  });
});
