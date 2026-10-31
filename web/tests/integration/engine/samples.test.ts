// End-to-end analysis of two real programs: the RSLogix 500 screenshot in samples/ and the
// motor/E-stop/timer/alarm program the old mock UI pretended to analyse.
import { describe, expect, it } from "vitest";
import { analyzeProgram, applyPatches, createSimulator, tagKey } from "../../../src/engine";
import { StInterpreter } from "../../helpers/st-interpreter";

// samples/ladder_logic_program_PLC1.webp, transcribed (contract case "numeric labels set rung numbers")
const RSLOGIX = "0000: XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);\n0001: [XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);\n0002: XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);";

describe("(a) RSLogix 500 sample", () => {
  const a = analyzeProgram(RSLOGIX);

  it("parses and traces all three rungs", () => {
    expect(a.parse.ok).toBe(true);
    expect(a.parse.rungs.map((r) => r.number)).toEqual([0, 1, 2]);
    expect(a.xref.outputs.map((o) => o.text)).toEqual(["I:1/1 AND I:1/2", "I:1/3 OR B:0/1", "NOT I:1/1 AND NOT I:1/2 AND NOT I:1/3"]);
    expect(a.stats).toMatchObject({ rungs: 3, inputs: 3, outputs: 3 });
  });

  it("raises only the honest low-severity findings", () => {
    expect(a.faults.findings.map((f) => f.rule)).toEqual(["MISSING_COMMENT"]);
    expect(a.faults.grade).toBe("Healthy");
  });

  it("simulates, and the generated ST agrees on all 8 input combinations", () => {
    const sim = createSimulator(a.parse.rungs);
    const vm = new StInterpreter(a.st.code);
    const id = (t: string) => a.st.identifiers[tagKey(t)];
    for (let mask = 0; mask < 8; mask++) {
      for (const [k, t] of ["I:1/1", "I:1/2", "I:1/3"].entries()) {
        sim.setInput(t, !!(mask & (1 << k)));
        vm.set(id(t), !!(mask & (1 << k)));
      }
      sim.scan(10);
      vm.scan(10);
      for (const t of ["B:0/1", "O:2/1", "O:2/2"]) expect(vm.get(id(t)), `${t} @ ${mask}`).toBe(sim.read(t));
    }
    // I:1/1 and I:1/2 on -> B:0/1 -> O:2/1, and O:2/2 off
    sim.setInput("I:1/1", true);
    sim.setInput("I:1/2", true);
    sim.setInput("I:1/3", false);
    sim.scan(10);
    expect([sim.read("B:0/1"), sim.read("O:2/1"), sim.read("O:2/2")]).toEqual([true, true, false]);
  });
});

// The program behind the v1 mock-up (src/app/lib/mockData.ts, removed in v2), written as LLT exactly as the mock drew it:
// rung 1 seal-in with an NC stop, rung 2 an overload timer whose preset is not visible,
// rung 3 an alarm gated by E-stop and the timer's done bit, rung 4 a reset button.
const LEGACY = [
  "[XIC(START_PB),XIC(MOTOR_OUT)]XIO(STOP_PB)OTE(MOTOR_OUT);",
  "XIC(MOTOR_OUT)XIC(OVL_FAULT)TON(DELAY_TMR,?,0);",
  "XIO(E_STOP)XIC(DELAY_TMR.DN)OTE(ALARM_OUT);",
  "XIC(RESET_PB)RES(DELAY_TMR);",
].join("\n");

// The old mock's "corrected" Structured Text called DELAY_TMR twice per scan
// (rung 2 and again inside IF RESET_PB ... DELAY_TMR(IN := FALSE)). As ladder that is:
const LEGACY_CORRECTED = [
  "[XIC(START_PB),XIC(MOTOR_OUT)]XIO(STOP_PB)XIO(E_STOP)OTE(MOTOR_OUT);",
  "XIC(MOTOR_OUT)XIC(OVL_FAULT)TON(DELAY_TMR,5000,0);",
  "XIO(E_STOP)XIC(DELAY_TMR.DN)OTL(ALARM_OUT);",
  "XIC(ACK_PB)OTU(ALARM_OUT);",
  "XIC(RESET_PB)XIO(MOTOR_OUT)TON(DELAY_TMR,5000,0);",
].join("\n");

describe("(b) legacy mock program", () => {
  const a = analyzeProgram(LEGACY);
  const rules = a.faults.findings.map((f) => f.rule);

  it("flags the E-stop handled in standard logic, with the safety standards", () => {
    const f = a.faults.findings.find((x) => x.rule === "ESTOP_IN_STANDARD_LOGIC")!;
    expect(f.severity).toBe("high");
    expect(f.tags).toEqual(["E_STOP"]);
    expect(f.standard).toMatch(/ISO 13850/);
  });

  it("flags stop devices examined with XIO (the NC/NO convention the mock got wrong)", () => {
    const f = a.faults.findings.filter((x) => x.rule === "STOP_EXAMINED_WITH_XIO").flatMap((x) => x.tags);
    expect(f.sort()).toEqual(["E_STOP", "STOP_PB"]);
  });

  it("flags the unreadable timer preset", () => {
    expect(rules).toContain("UNKNOWN_OPERANDS");
    // v2: the unread preset is still translated as T#0ms, but never silently any more
    expect(a.st.code).toMatch(/DELAY_TMR\(IN := MOTOR_OUT AND OVL_FAULT AND NOT DELAY_TMR_RST, PT := T#0ms \(\* \? unread preset \*\)\)/);
    expect(a.st.warnings[0]).toMatch(/Unread operands/);
  });

  it("flags the old corrected ST's double timer call and generates a single call", () => {
    const b = analyzeProgram(LEGACY_CORRECTED);
    const reuse = b.faults.findings.find((x) => x.rule === "TIMER_INSTANCE_REUSED")!;
    expect(reuse.severity).toBe("high");
    expect(reuse.rungs).toEqual([1, 4]);
    expect(b.st.code.split("\n").filter((l) => /^\s*DELAY_TMR\(/.test(l))).toHaveLength(1);
    expect(b.st.warnings.join(" ")).toMatch(/more than one timer instruction/);
  });

  it("keeps the advisory tone: no code patch for the E-stop, patches re-parse", () => {
    expect(a.corrections.patches.some((p) => p.rule === "ESTOP_IN_STANDARD_LOGIC")).toBe(false);
    const applied = applyPatches(a.parse.rungs, a.corrections.patches.filter((p) => p.autoApplicable));
    expect(applied.parse.errors).toEqual([]);
  });

  it("runs the generated ST", () => {
    const vm = new StInterpreter(a.st.code);
    vm.set("START_PB", true);
    vm.scan(100);
    expect(vm.get("MOTOR_OUT")).toBe(true);
  });
});
