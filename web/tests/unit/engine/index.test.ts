import { describe, expect, it } from "vitest";
import * as engine from "../../../src/engine";

describe("analyzeProgram", () => {
  const text = "// motor\n[XIC(Start_PB),XIC(Motor)]XIC(Stop_PB)XIO(OL)OTE(Motor);\nXIC(Motor)TON(T1,5000,0);\nXIC(T1.DN)CTU(C1,3,0);\nXIC(Reset)RES(C1);";

  it("runs the whole pipeline", () => {
    const a = engine.analyzeProgram(text);
    expect(a.parse.ok).toBe(true);
    expect(a.stats).toEqual({ rungs: 4, instructions: 11, tags: 5, inputs: 4, outputs: 1, timers: 1, counters: 1, parseErrors: 0 });
    expect(a.st.code).toMatch(/PROGRAM LogicLens/);
    expect(a.faults.checklist.TIMER_OVERFLOW.status).toBe("NOT_FOUND");
    expect(a.timingsMs.total).toBe(0);
  });

  it("is deterministic without a clock and measures with one", () => {
    expect(engine.analyzeProgram(text)).toEqual(engine.analyzeProgram(text));
    let t = 0;
    const a = engine.analyzeProgram(text, { now: () => (t += 1) });
    expect(a.timingsMs.total).toBe(5);
  });

  it("survives bad input", () => {
    const a = engine.analyzeProgram("XIC(A OTE(B);\nFOO(X);");
    expect(a.parse.ok).toBe(false);
    expect(a.stats.parseErrors).toBe(2);
    expect(a.faults.checklist.BROKEN_BRANCH.status).toBe("FOUND");
  });

  it("re-exports the public API", () => {
    for (const name of [
      "parseProgram",
      "printProgram",
      "buildXref",
      "analyzeExpr",
      "analyzeFaults",
      "createSimulator",
      "toStructuredText",
      "suggestCorrections",
      "applyPatches",
      "inferTypes",
      "tagKey",
      "CHECKLIST_KEYS",
    ]) {
      expect(engine).toHaveProperty(name);
    }
  });
});
