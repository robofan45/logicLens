import { describe, expect, it } from "vitest";
import { applyPatches, suggestCorrections } from "../../../src/engine/correct";
import { analyzeFaults } from "../../../src/engine/faults";
import { parseProgram } from "../../../src/engine/parse";

const fix = (text: string) => {
  const p = parseProgram(text);
  expect(p.errors).toEqual([]);
  const faults = analyzeFaults(p.rungs, p.errors);
  const c = suggestCorrections(p.rungs, faults);
  return { p, faults, c, patch: (rule: string) => c.patches.find((x) => x.rule === rule) };
};

describe("suggestCorrections", () => {
  it("merges duplicate coils into one OR rung and deletes the others", () => {
    const { p, patch } = fix("XIC(A)XIO(B)OTE(Lamp);\nXIC(C)OTE(Horn);\n[XIC(D),XIC(E)]OTE(Lamp);");
    const m = patch("DUPLICATE_OUTPUT")!;
    expect(m.autoApplicable).toBe(true);
    expect(m.after).toEqual(["[XIC(A)XIO(B),[XIC(D),XIC(E)]]OTE(Lamp);"]);
    expect(m.rungs).toEqual([0, 2]);
    const applied = applyPatches(p.rungs, [m]);
    expect(applied.parse.errors).toEqual([]);
    expect(applied.text).toBe("XIC(C)OTE(Horn);\n[XIC(A)XIO(B),[XIC(D),XIC(E)]]OTE(Lamp);");
  });

  it("only advises when a duplicate coil sits in a complex rung", () => {
    const { c } = fix("XIC(A)[OTE(Lamp),OTE(X)];\nXIC(B)OTE(Lamp);");
    expect(c.patches.find((x) => x.rule === "DUPLICATE_OUTPUT")).toBeUndefined();
    expect(c.advisories.find((a) => a.rule === "DUPLICATE_OUTPUT")?.note).toMatch(/too complex/);
  });

  it("adds a seal-in around the start contact", () => {
    const { p, patch } = fix("XIC(Start_PB)XIO(OL_Trip)OTE(Motor_Run);");
    const s = patch("MISSING_SEAL_IN")!;
    expect(s.after).toEqual(["[XIC(Start_PB),XIC(Motor_Run)]XIO(OL_Trip)OTE(Motor_Run);"]);
    expect(applyPatches(p.rungs, [s]).parse.ok).toBe(true);
  });

  it("repairs an empty-leg seal-in", () => {
    const { patch } = fix("XIC(Start_PB)[XIC(Motor_Run),]XIC(Stop_PB)OTE(Motor_Run);");
    expect(patch("BRANCH_BYPASSED")!.after).toEqual(["[XIC(Start_PB),XIC(Motor_Run)]XIC(Stop_PB)OTE(Motor_Run);"]);
  });

  it("removes redundant contacts and duplicate legs", () => {
    expect(fix("XIC(A)XIC(B)XIC(A)OTE(Y);").patch("REDUNDANT_CONTACT")!.after).toEqual(["XIC(A)XIC(B)OTE(Y);"]);
    expect(fix("XIC(A)[XIC(A)XIC(B),XIC(C)]OTE(Y);").patch("REDUNDANT_CONTACT")!.after).toEqual(["XIC(A)[XIC(B),XIC(C)]OTE(Y);"]);
    expect(fix("[XIC(B)XIC(C),XIC(B)XIC(C)]OTE(Y);").patch("REDUNDANT_CONTACT")!.after).toEqual(["XIC(B)XIC(C)OTE(Y);"]);
  });

  it("swaps XIO to XIC on stops but never automatically", () => {
    const s = fix("[XIC(Start),XIC(M)]XIO(Stop_PB)OTE(M);").patch("STOP_EXAMINED_WITH_XIO")!;
    expect(s.autoApplicable).toBe(false);
    expect(s.after).toEqual(["[XIC(Start),XIC(M)]XIC(Stop_PB)OTE(M);"]);
    expect(s.verification.join(" ")).toMatch(/wired NC/);
  });

  it("inserts reset templates with ? operands, not automatically", () => {
    const { p, patch } = fix("XIC(A)OTL(Alarm);\nXIC(PE)CTU(C1,10,0);");
    const latch = patch("LATCH_WITHOUT_UNLATCH")!;
    const ctr = patch("COUNTER_NO_RESET")!;
    expect([latch.autoApplicable, ctr.autoApplicable]).toEqual([false, false]);
    expect(latch.after).toEqual(["XIC(?)OTU(Alarm);"]);
    expect(ctr.after).toEqual(["XIC(?)RES(C1);"]);
    const applied = applyPatches(p.rungs, [latch, ctr]);
    expect(applied.parse.ok).toBe(true);
    expect(applied.text).toMatch(/\/\/ Reset Alarm \(added by LogicLens/);
  });

  it("never offers a code change for an emergency stop", () => {
    const { c } = fix("[XIC(Start),XIC(M)]XIC(E_STOP)OTE(M);");
    expect(c.patches.some((x) => x.rule === "ESTOP_IN_STANDARD_LOGIC")).toBe(false);
    expect(c.advisories.find((a) => a.rule === "ESTOP_IN_STANDARD_LOGIC")?.note).toMatch(/No code change/);
  });

  it("marks overlapping patches as not auto-applicable", () => {
    const { c } = fix("XIC(Start_PB)XIC(A)XIC(A)OTE(Motor_Run);\nXIC(B)OTE(Motor_Run);");
    const auto = c.patches.filter((x) => x.autoApplicable);
    const touched = auto.flatMap((x) => x.ops.map((o) => o.rungIndex));
    expect(new Set(touched).size).toBe(touched.length);
    expect(c.patches.some((x) => !x.autoApplicable && x.verification.some((v) => /Overlaps P\d/.test(v)))).toBe(true);
  });

  it("produces a program that re-parses after applying every auto patch", () => {
    const { p, c } = fix(
      "XIC(Start_PB)XIO(OL)OTE(Motor_Run);\nXIC(A)OTE(Lamp);\nXIC(B)OTE(Lamp);\nXIC(C)XIC(D)XIC(C)OTE(Y);\nXIC(Go)[XIC(Run),]OTE(Run);",
    );
    const applied = applyPatches(p.rungs, c.patches.filter((x) => x.autoApplicable));
    expect(applied.parse.errors).toEqual([]);
    const again = analyzeFaults(applied.parse.rungs, []);
    expect(again.findings.map((f) => f.rule)).not.toContain("DUPLICATE_OUTPUT");
  });
});
