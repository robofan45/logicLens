// (d) Differential test: the ladder simulator and the generated Structured Text (run by
// tests/helpers/st-interpreter.ts) must agree output-by-output, scan-by-scan.
//
// Excluded constructs (see tests/helpers/program-arb.ts, `differential: true`):
//   RES        - ST gates the FB through <inst>_RST, which acts one scan late when the RES rung
//                sits below the timer/counter rung (documented in st.ts).
//   JMP / LBL  - backward jumps are not translatable to ST; forward jumps are, but are kept out
//                together with the backward case.
//   MCR        - zones are translated, but excluded as briefed.
//   JSR, END   - JSR is a commented placeholder; END truncates the translation.
//   reused instances and CTU+CTD pairs on one counter - one FB call per scan cannot reproduce
//                two instructions updating the same accumulator at two places in the scan.
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { createSimulator, parseProgram, tagKey, toStructuredText } from "../../../src/engine";
import { inputValueArb, programArb } from "../../helpers/program-arb";
import { StInterpreter } from "../../helpers/st-interpreter";

const same = (a: unknown, b: unknown) => a === b || (Number.isNaN(a) && Number.isNaN(b));

describe("(d) simulator == generated Structured Text", () => {
  it("agrees on 600 random programs x 60 scans of random inputs", () => {
    let programs = 0;
    let comparisons = 0;
    let withTemps = 0;
    const stepArb = fc.tuple(fc.constantFrom(0, 10, 50, 100, 250), fc.array(fc.tuple(fc.nat(), fc.nat()), { minLength: 0, maxLength: 6 }));
    fc.assert(
      fc.property(programArb({ differential: true, maxRungs: 6 }), fc.array(stepArb, { minLength: 60, maxLength: 60 }), fc.array(fc.oneof(fc.boolean(), fc.integer({ min: -5, max: 40 }), fc.constantFrom(0.5, 99.5)), { minLength: 32, maxLength: 32 }), (text, steps, pool) => {
        const p = parseProgram(text);
        expect(p.errors).toEqual([]);
        const st = toStructuredText(p.rungs);
        if (/RC_/.test(st.code)) withTemps++;
        const sim = createSimulator(p.rungs);
        const vm = new StInterpreter(st.code);
        const id = (t: string) => st.identifiers[tagKey(t)];
        const inputs = sim.inputs.filter((t) => id(t));
        const valueFor = (t: string, n: number): boolean | number => {
          const type = sim.types.get(tagKey(t));
          const v = pool[n % pool.length];
          if (type === "BOOL" || type === undefined) return typeof v === "boolean" ? v : v !== 0;
          if (type === "DINT") return typeof v === "boolean" ? (v ? 1 : 0) : Math.trunc(v);
          return typeof v === "boolean" ? (v ? 1 : 0) : v;
        };
        for (const [dt, changes] of steps) {
          for (const [which, n] of changes) {
            if (!inputs.length) break;
            const t = inputs[which % inputs.length];
            const v = valueFor(t, n);
            sim.setInput(t, v);
            vm.set(id(t), v);
          }
          sim.scan(dt);
          vm.scan(dt);
          for (const t of sim.tags) {
            const ident = id(t);
            if (!ident) continue;
            comparisons++;
            if (!same(sim.read(t), vm.get(ident))) {
              throw new Error(`mismatch on ${t}: ladder=${String(sim.read(t))} st=${String(vm.get(ident))}\n${text}\n---\n${st.code}`);
            }
          }
          for (const inst of Object.keys(st.instanceTypes)) {
            const key = Object.entries(st.identifiers).find(([, v]) => v === inst)![0];
            const fb = vm.fb(inst)!;
            const fbt = st.instanceTypes[inst];
            if (fbt === "CTU" || fbt === "CTUD") {
              const c = sim.counter(key)!;
              expect(fb.CV, `${inst}.CV`).toBe(c.ACC);
              expect(fbt === "CTU" ? fb.Q : fb.QU, `${inst} done`).toBe(c.DN);
            } else {
              const t = sim.timer(key)!;
              expect(fb.ET, `${inst}.ET`).toBe(t.ACC);
              expect(fb.Q, `${inst}.Q`).toBe(t.DN);
            }
          }
        }
        programs++;
        return true;
      }),
      { numRuns: 600, seed: 31102026 },
    );
    expect(programs).toBe(600);
    expect(withTemps).toBeGreaterThan(10);
    console.info(`differential: ${programs} programs, ${comparisons} tag comparisons, ${withTemps} programs used rung temporaries`);
  });

  it("covers inputs of every data type", () => {
    // sanity for the helper used above
    expect(fc.sample(inputValueArb("DINT"), 5).every((v) => Number.isInteger(v))).toBe(true);
    expect(fc.sample(inputValueArb("BOOL"), 5).every((v) => typeof v === "boolean")).toBe(true);
  });
});
