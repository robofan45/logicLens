import { describe, expect, it } from "vitest";
import { analyzeFaults, CHECKLIST_KEYS, riskOf, type Finding } from "../../../src/engine/faults";
import { parseProgram } from "../../../src/engine/parse";

const run = (text: string, opts = {}) => {
  const p = parseProgram(text);
  return analyzeFaults(p.rungs, p.errors, opts);
};
const rules = (text: string) => run(text).findings.map((f) => f.rule);
const find = (text: string, rule: string): Finding | undefined => run(text).findings.find((f) => f.rule === rule);

// a tidy, commented, interlocked program that should raise nothing but MISSING-free notes
const CLEAN = [
  "// Motor start/stop with seal-in and overload",
  "[XIC(Start_PB),XIC(Motor_Run)]XIC(Stop_PB)XIO(OL_Trip)OTE(Motor_Run);",
].join("\n");

describe("DUPLICATE_OUTPUT", () => {
  it("fires when two rungs write one coil (last write wins)", () => {
    const f = find("XIC(A)OTE(Lamp);\nXIC(B)OTE(Lamp);", "DUPLICATE_OUTPUT")!;
    expect(f.severity).toBe("high");
    expect(f.rungs).toEqual([0, 1]);
    expect(f.description).toMatch(/rung 1 wins/);
  });

  it("is critical for physical outputs and counts NCOIL", () => {
    expect(find("XIC(A)OTE(O:2/0);\nXIC(B)NCOIL(O:2/0);", "DUPLICATE_OUTPUT")!.severity).toBe("critical");
  });

  it("does not fire for one writer or for latch pairs", () => {
    expect(rules("XIC(A)OTE(Lamp);\nXIC(Lamp)OTE(Horn);")).not.toContain("DUPLICATE_OUTPUT");
    expect(rules("XIC(A)OTL(X);\nXIC(B)OTU(X);")).not.toContain("DUPLICATE_OUTPUT");
  });
});

describe("MIXED_OUTPUT_TYPES", () => {
  it("fires when OTE and OTL/OTU share a tag", () => {
    expect(find("XIC(A)OTE(X);\nXIC(B)OTU(X);", "MIXED_OUTPUT_TYPES")?.severity).toBe("medium");
  });
  it("does not fire for OTL/OTU only", () => {
    expect(rules("XIC(A)OTL(X);\nXIC(B)OTU(X);")).not.toContain("MIXED_OUTPUT_TYPES");
  });
});

describe("LATCH_WITHOUT_UNLATCH / UNLATCH_WITHOUT_LATCH", () => {
  it("fires for a latch nobody clears", () => {
    expect(find("XIC(A)OTL(Alarm);", "LATCH_WITHOUT_UNLATCH")?.severity).toBe("high");
  });
  it("accepts OTU, OTE or a MOV as a clearing path", () => {
    expect(rules("XIC(A)OTL(Alarm);\nXIC(Ack)OTU(Alarm);")).not.toContain("LATCH_WITHOUT_UNLATCH");
    expect(rules("XIC(A)OTL(W);\nXIC(B)MOV(0,W);")).not.toContain("LATCH_WITHOUT_UNLATCH");
  });
  it("flags an unlatch with no latch as low", () => {
    expect(find("XIC(A)OTU(Alarm);", "UNLATCH_WITHOUT_LATCH")?.severity).toBe("low");
    expect(rules("XIC(A)OTL(X);\nXIC(B)OTU(X);")).not.toContain("UNLATCH_WITHOUT_LATCH");
  });
});

describe("TIMER_INSTANCE_REUSED", () => {
  it("fires when one timer is driven twice (the old mock's ST bug)", () => {
    const f = find("XIC(Motor)XIC(OVL)TON(DELAY_TMR,5000,0);\nXIC(Reset)TON(DELAY_TMR,5000,0);", "TIMER_INSTANCE_REUSED")!;
    expect(f.severity).toBe("high");
    expect(f.rungs).toEqual([0, 1]);
  });
  it("fires for mixed timer types", () => {
    expect(rules("XIC(A)TON(T1,100,0);\nXIC(B)TOF(T1,100,0);")).toContain("TIMER_INSTANCE_REUSED");
  });
  it("accepts the Rockwell CTU + CTD up/down pattern", () => {
    expect(rules("XIC(In)CTU(C1,10,0);\nXIC(Out)CTD(C1,10,0);\nXIC(R)RES(C1);")).not.toContain("TIMER_INSTANCE_REUSED");
  });
});

describe("TIMER_PRESET_INVALID", () => {
  it.each([
    ["XIC(A)TON(T1,0,0);", "high"],
    ["XIC(A)TON(T1,-5,0);", "high"],
    ["XIC(A)TON(T1,3000000000,0);", "high"],
    ["XIC(A)TON(T4:0,0.001,40000,0);", "high"],
    ["XIC(A)TON(T1,Preset_Tag,0);", "low"],
  ])("%s -> %s", (text, sev) => {
    expect(find(text, "TIMER_PRESET_INVALID")?.severity).toBe(sev);
  });
  it("accepts sane presets in every syntax", () => {
    expect(rules("XIC(A)TON(T1,5000,0);\nXIC(B)TON(T4:0,0.01,500,0);\nXIC(C)TON(T2,T#5s);")).not.toContain("TIMER_PRESET_INVALID");
  });
});

describe("COUNTER_PRESET_INVALID and COUNTER_NO_RESET", () => {
  it("flags zero and overflowing presets", () => {
    expect(find("XIC(A)CTU(C1,0,0);\nXIC(R)RES(C1);", "COUNTER_PRESET_INVALID")?.severity).toBe("medium");
    expect(find("XIC(A)CTU(C1,9999999999,0);\nXIC(R)RES(C1);", "COUNTER_PRESET_INVALID")?.severity).toBe("high");
  });
  it("flags a counter that never resets", () => {
    expect(find("XIC(PE)CTU(C1,10,0);", "COUNTER_NO_RESET")?.severity).toBe("medium");
  });
  it("accepts RES or a MOV into the accumulator", () => {
    expect(rules("XIC(PE)CTU(C1,10,0);\nXIC(R)RES(C1);")).not.toContain("COUNTER_NO_RESET");
    expect(rules("XIC(PE)CTU(C1,10,0);\nXIC(R)MOV(0,C1.ACC);")).not.toContain("COUNTER_NO_RESET");
  });
  it("flags a retentive timer that never resets", () => {
    expect(find("XIC(A)RTO(T1,1000,0);", "RTO_NO_RESET")?.severity).toBe("medium");
    expect(rules("XIC(A)RTO(T1,1000,0);\nXIC(R)RES(T1);")).not.toContain("RTO_NO_RESET");
  });
});

describe("DEAD_RUNG, CONTRADICTORY_CONTACTS, ALWAYS_TRUE, UNCONDITIONAL_OUTPUT", () => {
  it("fires DEAD_RUNG for an unsatisfiable condition", () => {
    const f = find("XIC(A)XIO(A)OTE(Y);", "DEAD_RUNG")!;
    expect(f.severity).toBe("medium");
    expect(f.basis).toBe("rule");
  });
  it("fires DEAD_RUNG through numeric contradictions", () => {
    expect(rules("GRT(Level,80)LES(Level,50)OTE(Pump);")).toContain("DEAD_RUNG");
  });
  it("treats AFI as a deliberate disable (low)", () => {
    expect(find("AFI()XIC(A)OTE(Y);", "DEAD_RUNG")?.severity).toBe("low");
  });
  it("fires CONTRADICTORY_CONTACTS for one dead leg in an otherwise live rung", () => {
    const fs = run("XIC(A)[XIO(A)XIC(B),XIC(C)]OTE(Y);").findings.map((f) => f.rule);
    expect(fs).toContain("CONTRADICTORY_CONTACTS");
    expect(fs).not.toContain("DEAD_RUNG");
  });
  it("fires ALWAYS_TRUE for a tautology or an empty-leg bypass", () => {
    expect(rules("[XIC(A),XIO(A)]OTE(Y);")).toContain("ALWAYS_TRUE");
    expect(rules("[XIC(A),]OTE(Y);")).toContain("ALWAYS_TRUE");
    expect(rules("GRT(5,3)OTE(Y);")).toContain("ALWAYS_TRUE");
  });
  it("fires UNCONDITIONAL_OUTPUT for an output with no inputs, but not for MCR/END/NOP/JSR", () => {
    expect(find("OTE(Y);", "UNCONDITIONAL_OUTPUT")?.severity).toBe("low");
    expect(rules("XIC(Z)MCR();\nXIC(A)OTE(B);\nMCR();\nJSR(Main);\nNOP();\nEND();")).not.toContain("UNCONDITIONAL_OUTPUT");
  });
  it("stays quiet on ordinary logic", () => {
    const fs = rules("XIC(A)XIO(B)OTE(Y);");
    for (const r of ["DEAD_RUNG", "CONTRADICTORY_CONTACTS", "ALWAYS_TRUE", "UNCONDITIONAL_OUTPUT"]) expect(fs).not.toContain(r);
  });
});

describe("BRANCH_BYPASSED", () => {
  it("fires when an empty leg makes a parallel contact useless (broken seal-in)", () => {
    const f = find("XIC(Start_PB)[XIC(Motor_Run),]XIC(Stop_PB)OTE(Motor_Run);", "BRANCH_BYPASSED")!;
    expect(f.severity).toBe("medium");
    expect(f.tags).toEqual(["Motor_Run"]);
    expect(f.checklist).toBe("ALWAYS_TRUE");
  });
  it("does not double-report a rung that is already always true", () => {
    const fs = rules("[XIC(A),]OTE(Y);");
    expect(fs).toContain("ALWAYS_TRUE");
    expect(fs).not.toContain("BRANCH_BYPASSED");
  });
  it("does not fire for full branches", () => {
    expect(rules("[XIC(A),XIC(B)]OTE(Y);")).not.toContain("BRANCH_BYPASSED");
  });
});

describe("MISSING_SEAL_IN", () => {
  it("fires for a momentary start that drives a motor directly", () => {
    const f = find("XIC(Start_PB)XIO(Stop_PB)OTE(Motor_Run);", "MISSING_SEAL_IN")!;
    expect(f.basis).toBe("heuristic");
    expect(f.confidence).toBeLessThanOrEqual(65);
  });
  it("does not fire with a seal-in contact, a latch, an edge or an indicator", () => {
    expect(rules(CLEAN)).not.toContain("MISSING_SEAL_IN");
    expect(rules("XIC(Start_PB)OTL(Motor_Run);\nXIC(Stop_PB)OTU(Motor_Run);")).not.toContain("MISSING_SEAL_IN");
    expect(rules("XIC(Start_PB)OTE(Start_Lamp);")).not.toContain("MISSING_SEAL_IN");
  });
});

describe("MISSING_INTERLOCK", () => {
  it("fires for an actuator with no stop or permissive in its condition", () => {
    expect(find("XIC(Auto_Mode)OTE(Pump_P101);", "MISSING_INTERLOCK")?.confidence).toBeLessThanOrEqual(60);
  });
  it("is satisfied by a stop, a permissive tag or a compare", () => {
    expect(rules(CLEAN)).not.toContain("MISSING_INTERLOCK");
    expect(rules("XIC(Auto_Mode)XIO(Tank_Low)OTE(Pump_P101);")).not.toContain("MISSING_INTERLOCK");
    expect(rules("XIC(Auto_Mode)GRT(Level,10)OTE(Pump_P101);")).not.toContain("MISSING_INTERLOCK");
  });
  it("looks at the unlatch rung for latched actuators", () => {
    expect(rules("XIC(Auto)OTL(Pump_P101);\nXIC(Stop_PB)OTU(Pump_P101);")).not.toContain("MISSING_INTERLOCK");
    expect(rules("XIC(Auto)OTL(Pump_P101);\nXIC(Done)OTU(Pump_P101);")).toContain("MISSING_INTERLOCK");
  });
});

describe("ESTOP_IN_STANDARD_LOGIC and STOP_EXAMINED_WITH_XIO", () => {
  it("raises one high, heuristic E-stop verification finding citing the standards", () => {
    const fs = run("[XIC(Start),XIC(Motor)]XIC(E_STOP)OTE(Motor);\nXIO(E_STOP)OTE(Alarm_Lamp);").findings.filter(
      (f) => f.rule === "ESTOP_IN_STANDARD_LOGIC",
    );
    expect(fs).toHaveLength(1);
    expect(fs[0].severity).toBe("high");
    expect(fs[0].standard).toMatch(/ISO 13850/);
    expect(fs[0].description).toMatch(/hard-wired|safety-rated/);
  });
  it("flags a stop button examined with XIO (not fail-safe)", () => {
    const f = find("[XIC(Start),XIC(Motor)]XIO(Stop_PB)OTE(Motor);", "STOP_EXAMINED_WITH_XIO")!;
    expect(f.severity).toBe("medium");
    expect(f.checklist).toBe("WRONG_CONTACT_TYPE");
  });
  it("needs a stop-like name, ignores internal addresses, and accepts XIC on stops", () => {
    expect(find("[XIC(Start),XIC(M)]XIO(I:1/2)OTE(M);", "STOP_EXAMINED_WITH_XIO")).toBeUndefined();
    expect(rules("XIC(A)XIO(B3:0/5)OTE(M);")).not.toContain("STOP_EXAMINED_WITH_XIO");
    expect(rules("XIC(A)XIO(%M10.0)OTE(M);")).not.toContain("STOP_EXAMINED_WITH_XIO");
    expect(rules(CLEAN)).not.toContain("STOP_EXAMINED_WITH_XIO");
    expect(find("XIC(Start)XIO(Stop_PB)OTE(M);", "STOP_EXAMINED_WITH_XIO")!.confidence).toBeLessThanOrEqual(70);
  });
  it("leaves HMI/command stop bits alone", () => {
    expect(rules("[XIC(Start),XIC(M)]XIO(Stop_Cmd)OTE(M);")).not.toContain("STOP_EXAMINED_WITH_XIO");
    expect(rules("[XIC(Start),XIC(M)]XIO(HMI_Stop)OTE(M);")).not.toContain("STOP_EXAMINED_WITH_XIO");
  });
});

describe("REDUNDANT_CONTACT", () => {
  it("fires for the same contact twice on a path and for identical legs", () => {
    expect(rules("XIC(A)XIC(B)XIC(A)OTE(Y);")).toContain("REDUNDANT_CONTACT");
    expect(rules("XIC(A)[XIC(A)XIC(B),XIC(C)]OTE(Y);")).toContain("REDUNDANT_CONTACT");
    expect(rules("[XIC(B)XIC(C),XIC(B)XIC(C)]OTE(Y);")).toContain("REDUNDANT_CONTACT");
  });
  it("does not fire when an output rewrites the tag between the two reads", () => {
    expect(rules("XIC(B)XIC(X)OTE(B)XIC(B)OTE(C);")).not.toContain("REDUNDANT_CONTACT");
    expect(rules("[XIC(Start),XIC(Motor)]XIC(Motor)OTE(Motor);")).toContain("REDUNDANT_CONTACT");
  });
  it("does not fire for the same tag on different legs", () => {
    expect(rules("[XIC(A)XIC(B),XIC(A)XIC(C)]OTE(Y);")).not.toContain("REDUNDANT_CONTACT");
  });
});

describe("SCAN_ORDER_DELAY and UNUSED_INTERNAL", () => {
  it("aggregates scan-order notes", () => {
    const f = find("XIC(Aux_Flag)OTE(Lamp);\nXIC(Step_A)OTE(Horn);\nXIC(Start)OTE(Aux_Flag);\nXIC(B)OTE(Step_A);", "SCAN_ORDER_DELAY")!;
    expect(f.severity).toBe("low");
    expect(f.tags).toEqual(["Aux_Flag", "Step_A"]);
  });
  it("flags internal bits that are written but never read", () => {
    const f = find("XIC(A)OTE(B3:0/1);\nXIC(B)OTE(Aux_Flag);\nXIC(C)OTE(Motor);", "UNUSED_INTERNAL")!;
    expect(f.tags).toEqual(["B3:0/1", "Aux_Flag"]);
  });
  it("does not flag physical outputs or read bits", () => {
    expect(rules("XIC(A)OTE(O:2/0);\nXIC(B)OTE(B3:0/1);\nXIC(B3:0/1)OTE(Lamp);")).not.toContain("UNUSED_INTERNAL");
  });
});

describe("UNDEFINED_TIMER_REFERENCE", () => {
  it("fires for a done bit with no timer in the program", () => {
    expect(find("XIC(T4:0/DN)OTE(Lamp);", "UNDEFINED_TIMER_REFERENCE")?.confidence).toBeGreaterThanOrEqual(80);
    expect(find("XIC(Fill_Tmr.DN)OTE(Lamp);", "UNDEFINED_TIMER_REFERENCE")?.severity).toBe("medium");
  });
  it("does not fire when the timer exists or the member is a UDT field", () => {
    expect(rules("XIC(A)TON(T1,10,0);\nXIC(T1.DN)OTE(L);")).not.toContain("UNDEFINED_TIMER_REFERENCE");
    expect(rules("XIC(Valve.EN)OTE(L);\nXIC(Motor.Run)OTE(K);")).not.toContain("UNDEFINED_TIMER_REFERENCE");
  });
});

describe("jumps, labels, MCR", () => {
  it("flags a missing jump target", () => {
    expect(find("XIC(A)JMP(L9);\nXIC(B)OTE(C);", "JUMP_TARGET_MISSING")?.severity).toBe("high");
  });
  it("flags a label that is not first and a backward jump", () => {
    expect(find("XIC(A)LBL(L1)OTE(B);\nXIC(C)JMP(L1);", "LBL_NOT_FIRST")?.severity).toBe("medium");
    expect(rules("LBL(L1)XIC(A)OTE(B);\nXIC(C)JMP(L1);")).toContain("BACKWARD_JUMP");
    expect(rules("XIC(C)JMP(L1);\nXIC(A)OTE(B);\nLBL(L1)XIC(D)OTE(E);")).toEqual(
      expect.not.arrayContaining(["JUMP_TARGET_MISSING", "LBL_NOT_FIRST", "BACKWARD_JUMP"]),
    );
  });
  it("flags a duplicated label", () => {
    expect(rules("XIC(C)JMP(L1);\nLBL(L1)XIC(A)OTE(B);\nLBL(L1)XIC(D)OTE(E);")).toContain("LABEL_DUPLICATE");
  });
  it("flags an MCR zone that never ends or nests", () => {
    expect(find("XIC(Z)MCR();\nXIC(A)OTE(B);", "MCR_UNBALANCED")?.severity).toBe("high");
    expect(rules("XIC(Z)MCR();\nXIC(Y)MCR();\nMCR();")).toContain("MCR_UNBALANCED");
    expect(rules("XIC(Z)MCR();\nXIC(A)OTE(B);\nMCR();")).not.toContain("MCR_UNBALANCED");
  });
});

describe("ONE_SHOT_STORAGE_REUSED, DIVIDE_BY_ZERO, UNKNOWN_OPERANDS", () => {
  it("flags one storage bit shared by two one-shots or also driven by a coil", () => {
    expect(find("XIC(A)ONS(OS1)OTE(B);\nXIC(C)OSR(OS1,D);", "ONE_SHOT_STORAGE_REUSED")?.severity).toBe("high");
    expect(rules("XIC(A)ONS(OS1)OTE(B);\nXIC(C)OTE(OS1);")).toContain("ONE_SHOT_STORAGE_REUSED");
    expect(rules("XIC(A)ONS(OS1)OTE(B);\nXIC(C)ONS(OS2)OTE(D);")).not.toContain("ONE_SHOT_STORAGE_REUSED");
  });
  it("flags a literal zero divisor", () => {
    expect(find("XIC(A)DIV(X,0,Y);", "DIVIDE_BY_ZERO")?.severity).toBe("high");
    expect(rules("XIC(A)DIV(X,2,Y);")).not.toContain("DIVIDE_BY_ZERO");
  });
  it("aggregates unreadable operands", () => {
    const f = find("XIC(?)OTE(B);\nXIC(C)OTE(?);", "UNKNOWN_OPERANDS")!;
    expect(f.severity).toBe("medium");
    expect(f.rungs).toEqual([0, 1]);
  });
});

describe("MISSING_COMMENT and NAMING_INCONSISTENCY", () => {
  it("raises one aggregated missing-comment finding", () => {
    const fs = run("XIC(A)OTE(B);\nXIC(C)OTE(D);\n// ok\nXIC(E)OTE(F);").findings.filter((f) => f.rule === "MISSING_COMMENT");
    expect(fs).toHaveLength(1);
    expect(fs[0].rungs).toEqual([0, 1]);
    expect(fs[0].title).toMatch(/2 of 3 rungs/);
  });
  it("flags mixed address and symbolic naming once", () => {
    const fs = run("XIC(I:1/0)XIC(Start_PB)OTE(Motor);").findings.filter((f) => f.rule === "NAMING_INCONSISTENCY");
    expect(fs).toHaveLength(1);
  });
  it("flags mixed snake_case and CamelCase", () => {
    expect(rules("XIC(Start_PB)XIC(Stop_PB)XIC(MotorReady)XIC(PumpReady)OTE(Run_Cmd);")).toContain("NAMING_INCONSISTENCY");
  });
  it("accepts a consistent style", () => {
    expect(rules("// a\nXIC(Start_PB)XIC(Stop_PB)OTE(Run_Cmd);")).not.toContain("NAMING_INCONSISTENCY");
  });
});

describe("checklist, risk and counts", () => {
  it("covers the 19 Playbook items", () => {
    expect(CHECKLIST_KEYS).toHaveLength(19);
    const r = run(CLEAN);
    expect(Object.keys(r.checklist).sort()).toEqual([...CHECKLIST_KEYS].sort());
    expect(r.checklist.MISSING_SAFETY_INPUT.status).toBe("NOT_APPLICABLE");
    expect(r.checklist.BYPASSED_SAFETY.reason).toMatch(/SIS|SRS/);
    expect(r.checklist.COUNTER_NO_RESET.status).toBe("NOT_APPLICABLE");
    expect(r.checklist.COIL_CONFLICT.status).toBe("NOT_FOUND");
  });

  it("marks FOUND items with their finding ids", () => {
    const r = run("XIC(A)OTE(Lamp);\nXIC(B)OTE(Lamp);");
    expect(r.checklist.COIL_CONFLICT.status).toBe("FOUND");
    expect(r.checklist.RACE_CONDITION.findings.length).toBeGreaterThan(0);
  });

  it("marks BROKEN_BRANCH from unbalanced parse errors", () => {
    expect(run("[XIC(A),XIC(B)OTE(C);").checklist.BROKEN_BRANCH.status).toBe("FOUND");
    expect(run("XIC(A)OTE(B);").checklist.BROKEN_BRANCH.status).toBe("NOT_FOUND");
  });

  it("combines weights into a 0-100 risk score with grades", () => {
    expect(riskOf([])).toEqual({ riskScore: 0, grade: "Healthy" });
    expect(riskOf(["critical"])).toEqual({ riskScore: 45, grade: "Minor issues" });
    expect(riskOf(["critical", "high"]).riskScore).toBe(59);
    expect(riskOf(["critical", "critical", "high"]).grade).toBe("Critical");
    expect(riskOf(["low"]).grade).toBe("Healthy");
  });

  it("orders findings by severity and numbers them", () => {
    const r = run("XIC(A)OTE(O:2/0);\nXIC(B)OTE(O:2/0);\nXIC(C)OTE(D);");
    const sev = r.findings.map((f) => f.severity);
    const rank = { critical: 0, high: 1, medium: 2, low: 3 };
    expect([...sev].sort((a, b) => rank[a] - rank[b])).toEqual(sev);
    expect(r.findings.map((f) => f.id)).toEqual(r.findings.map((_, i) => `F${i + 1}`));
    expect(r.counts.total).toBe(r.findings.length);
  });

  it("is deterministic", () => {
    const t = "XIC(Start_PB)XIO(Stop_PB)OTE(Motor_Run);\nXIC(E_STOP)OTE(Alarm);\nXIC(A)OTE(Alarm);";
    expect(run(t)).toEqual(run(t));
  });

  it("never cites a clause number", () => {
    const t = "XIC(Start_PB)XIO(Stop_PB)XIC(E_STOP)OTE(Motor_Run);\nXIC(A)OTE(Motor_Run);\nXIC(B)TON(T1,0,0);\nXIC(C)OTL(X);";
    for (const f of run(t).findings) expect(`${f.standard ?? ""} ${f.description}`).not.toMatch(/§|clause|\b\d+\.\d+\.\d+/i);
  });
});
