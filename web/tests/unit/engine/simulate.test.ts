import { describe, expect, it } from "vitest";
import { parseProgram } from "../../../src/engine/parse";
import { createSimulator } from "../../../src/engine/simulate";

const sim = (text: string) => {
  const p = parseProgram(text);
  expect(p.errors).toEqual([]);
  return createSimulator(p.rungs);
};

describe("bits, seal-in and latches", () => {
  it("runs a fail-safe start/stop circuit", () => {
    const s = sim("[XIC(Start_PB),XIC(Motor)]XIC(Stop_PB)OTE(Motor);");
    expect(s.inputs).toEqual(["Start_PB", "Stop_PB"]);
    s.setInput("Stop_PB", true); // NC stop button, healthy
    s.scan(10);
    expect(s.read("Motor")).toBe(false);
    s.setInput("Start_PB", true);
    s.scan(10);
    expect(s.read("Motor")).toBe(true);
    s.setInput("Start_PB", false);
    s.scan(10);
    expect(s.read("Motor")).toBe(true); // sealed in
    s.setInput("Stop_PB", false); // pressed (or wire broken)
    const r = s.scan(10);
    expect(s.read("Motor")).toBe(false);
    expect(r.changed).toContain("Motor");
  });

  it("latches and unlatches", () => {
    const s = sim("XIC(A)OTL(L);\nXIC(B)OTU(L);");
    s.setInput("A", true);
    s.scan(0);
    s.setInput("A", false);
    s.scan(0);
    expect(s.read("L")).toBe(true);
    s.setInput("B", true);
    s.scan(0);
    expect(s.read("L")).toBe(false);
  });

  it("evaluates mid-rung outputs and branch legs in order (writes visible immediately)", () => {
    const s = sim("XIC(A)OTE(B)XIC(B)OTE(C);\n[XIC(A)OTE(D),XIC(D)OTE(E)];\nNCOIL(F);");
    s.setInput("A", true);
    s.scan(0);
    expect([s.read("B"), s.read("C"), s.read("D"), s.read("E"), s.read("F")]).toEqual([true, true, true, true, false]);
  });

  it("reports per-instruction power for highlighting", () => {
    const s = sim("XIC(A)XIO(B)OTE(C);");
    s.setInput("A", true);
    s.setInput("B", true);
    const r = s.scan(0);
    expect(r.power).toEqual({
      r0i0: { in: true, out: true },
      r0i1: { in: true, out: false },
      r0i2: { in: false, out: false },
    });
  });
});

describe("timers", () => {
  it("TON: the enabling scan contributes 0 ms", () => {
    const s = sim("XIC(A)TON(T1,300,0);\nXIC(T1.DN)OTE(Done);");
    s.setInput("A", true);
    const acc: number[] = [];
    for (let k = 0; k < 5; k++) {
      s.scan(100);
      acc.push(s.timer("T1")!.ACC);
    }
    expect(acc).toEqual([0, 100, 200, 300, 300]);
    expect(s.read("Done")).toBe(true);
    expect(s.read("T1.TT")).toBe(false);
    s.setInput("A", false);
    s.scan(100);
    expect(s.timer("T1")).toMatchObject({ ACC: 0, DN: false, EN: false });
  });

  it("TON with a zero preset is done on the enabling scan; SLC and IEC forms agree", () => {
    const s = sim("XIC(A)TON(T1,0,0);\nXIC(A)TON(T4:0,0.01,20,0);\nXIC(A)TON(T2,T#200ms);");
    s.setInput("A", true);
    s.scan(100);
    expect(s.read("T1.DN")).toBe(true);
    s.scan(100);
    s.scan(100);
    expect([s.read("T4:0/DN"), s.read("T2.Q"), s.read("T2.ET")]).toEqual([true, true, 200]);
  });

  it("TOF keeps DN on for the preset after the rung goes false", () => {
    const s = sim("XIC(A)TOF(T1,200,0);");
    s.setInput("A", true);
    s.scan(100);
    expect(s.read("T1.DN")).toBe(true);
    s.setInput("A", false);
    const dn: boolean[] = [];
    for (let k = 0; k < 4; k++) {
      s.scan(100);
      dn.push(s.readBit("T1.DN"));
    }
    expect(dn).toEqual([true, true, false, false]);
  });

  it("RTO retains its accumulator and RES clears it", () => {
    const s = sim("XIC(A)RTO(T1,250,0);\nXIC(R)RES(T1);");
    s.setInput("A", true);
    s.scan(100);
    s.scan(100);
    s.setInput("A", false);
    s.scan(100);
    expect(s.timer("T1")!.ACC).toBe(100);
    s.setInput("A", true);
    s.scan(100); // re-enabling scan adds nothing
    s.scan(100);
    s.scan(100);
    expect(s.timer("T1")).toMatchObject({ ACC: 250, DN: true });
    s.setInput("R", true);
    s.scan(100);
    expect(s.timer("T1")).toMatchObject({ ACC: 0, DN: false });
  });

  it("TP produces one pulse per rising edge", () => {
    const s = sim("XIC(A)TP(T1,200);\nXIC(T1.Q)OTE(Pulse);");
    const seq: boolean[] = [];
    const a = [true, true, true, true, false, true, false];
    for (const v of a) {
      s.setInput("A", v);
      s.scan(100);
      seq.push(s.readBit("Pulse"));
    }
    expect(seq).toEqual([true, true, false, false, false, true, true]);
  });

  it("reads a runtime preset from a tag", () => {
    const s = sim("XIC(A)TON(T1,Pre,0);");
    s.setInput("Pre", 100);
    s.setInput("A", true);
    s.scan(100);
    s.scan(100);
    expect(s.read("T1.DN")).toBe(true);
  });
});

describe("counters", () => {
  it("CTU counts rising edges, RES resets", () => {
    const s = sim("XIC(PE)CTU(C1,3,0);\nXIC(R)RES(C1);\nXIC(C1.DN)OTE(Full);");
    for (const v of [true, true, false, true, false, true]) {
      s.setInput("PE", v);
      s.scan(10);
    }
    expect(s.counter("C1")).toMatchObject({ ACC: 3, DN: true });
    expect(s.read("Full")).toBe(true);
    s.setInput("R", true);
    s.scan(10);
    expect(s.counter("C1")).toMatchObject({ ACC: 0, DN: false });
  });

  it("CTU + CTD share one accumulator (Rockwell up/down pattern)", () => {
    const s = sim("XIC(In)CTU(C1,2,0);\nXIC(Out)CTD(C1,2,0);");
    for (const [i, o] of [[true, false], [false, false], [true, false], [false, true]]) {
      s.setInput("In", i);
      s.setInput("Out", o);
      s.scan(0);
    }
    expect(s.counter("C1")!.ACC).toBe(1);
  });

  it("CTUD counts up on the rung and down on its third operand; simultaneous edges cancel", () => {
    const s = sim("XIC(Up)CTUD(C1,5,Down);");
    const steps: [boolean, boolean][] = [[true, false], [false, false], [true, false], [false, true], [false, false], [true, true]];
    for (const [u, d] of steps) {
      s.setInput("Up", u);
      s.setInput("Down", d);
      s.scan(0);
    }
    expect(s.counter("C1")!.ACC).toBe(1);
    expect(s.read("C1.CV")).toBe(1);
  });
});

describe("one-shots and edges", () => {
  it("ONS, OSR, OSF, P and N pulse for exactly one scan", () => {
    const s = sim("XIC(A)ONS(S1)OTE(O1);\nXIC(A)OSR(S2,O2);\nXIC(A)OSF(S3,O3);\nP(A)OTE(O4);\nN(A)OTE(O5);");
    const trace: string[] = [];
    for (const v of [false, true, true, false, false]) {
      s.setInput("A", v);
      s.scan(0);
      trace.push(["O1", "O2", "O3", "O4", "O5"].map((t) => (s.readBit(t) ? 1 : 0)).join(""));
    }
    expect(trace).toEqual(["00000", "11010", "00000", "00101", "00000"]);
  });
});

describe("numbers", () => {
  it("does math, moves, compares and circular limits", () => {
    const s = sim(
      "XIC(Go)ADD(Count,1,Count);\nMOV(Count,Copy);\nGRT(Count,1)OTE(Many);\nLIM(10,Level,20)OTE(InBand);\nLIM(20,Level,10)OTE(OutBand);\nXIC(Go)DIV(Count,0,Zero);",
    );
    s.setInput("Go", true);
    s.setInput("Level", 15);
    s.scan(0);
    const r = s.scan(0);
    expect([s.read("Count"), s.read("Copy"), s.read("Many"), s.read("InBand"), s.read("OutBand"), s.read("Zero")]).toEqual([
      2,
      2,
      true,
      true,
      false,
      0,
    ]);
    expect(r.warnings.join(" ")).toMatch(/Division by zero/);
  });

  it("truncates and wraps DINT tags but keeps REAL fractions", () => {
    const s = sim("MOV(7.9,N7:0);\nMOV(7.9,Real1);\nMOV(3000000000,N7:1);\nXIC(A)AND(N7:0,6,W);\nNOT(0,W2);");
    s.scan(0);
    expect([s.read("N7:0"), s.read("Real1"), s.read("N7:1"), s.read("W"), s.read("W2")]).toEqual([7, 7.9, -1294967296, 0, -1]);
    expect(s.types.get("W")).toBe("DINT");
  });
});

describe("program flow", () => {
  it("forward JMP skips rungs up to the label", () => {
    const s = sim("XIC(Skip)JMP(L1);\nXIC(A)OTE(B);\nLBL(L1)XIC(A)OTE(C);");
    s.setInput("A", true);
    s.setInput("Skip", true);
    const r = s.scan(0);
    expect([s.read("B"), s.read("C")]).toEqual([false, true]);
    expect(r.executedRungs).toEqual([0, 2]);
  });

  it("a backward jump loop trips the watchdog instead of hanging", () => {
    const p = parseProgram("LBL(Top)XIC(A)OTE(B);\nXIC(Loop)JMP(Top);");
    const s = createSimulator(p.rungs, { maxExecutionsPerScan: 1000 });
    s.setInput("Loop", true);
    expect(s.scan(0).fault).toMatch(/WATCHDOG/);
  });

  it("warns once for a missing jump target and for JSR", () => {
    const s = sim("XIC(A)JMP(Nowhere);\nXIC(A)JSR(Sub1);\nXIC(A)OTE(B);");
    s.setInput("A", true);
    const r = s.scan(0);
    expect(r.warnings.some((w) => /not found/.test(w))).toBe(true);
    expect(r.warnings.some((w) => /JSR\(Sub1\)/.test(w))).toBe(true);
    expect(s.scan(0).warnings.some((w) => /JSR/.test(w))).toBe(false);
    expect(s.read("B")).toBe(true);
  });

  it("an MCR zone forces its rungs false but keeps latches", () => {
    const s = sim("XIC(Zone)MCR();\nXIC(A)OTE(B);\nXIC(A)OTL(L);\nMCR();\nXIC(A)OTE(After);");
    s.setInput("Zone", true);
    s.setInput("A", true);
    s.scan(0);
    expect([s.read("B"), s.read("L"), s.read("After")]).toEqual([true, true, true]);
    s.setInput("Zone", false);
    s.scan(0);
    expect([s.read("B"), s.read("L"), s.read("After")]).toEqual([false, true, true]);
  });

  it("END stops the scan", () => {
    const s = sim("XIC(A)OTE(B);\nEND();\nXIC(A)OTE(C);");
    s.setInput("A", true);
    s.scan(0);
    expect([s.read("B"), s.read("C")]).toEqual([true, false]);
  });

  it("AFI disables a rung", () => {
    const s = sim("AFI()OTE(B);\nAFI()NCOIL(C);\nNOP();");
    s.scan(0);
    expect([s.read("B"), s.read("C")]).toEqual([false, true]);
  });
});

describe("forcing, snapshot and reset", () => {
  it("forces override reads and block program writes", () => {
    const s = sim("XIC(A)OTE(B);");
    s.force("B", true);
    s.scan(0);
    expect(s.read("B")).toBe(true);
    expect(s.forced()).toEqual({ B: true });
    s.force("B", null);
    s.scan(0);
    expect(s.read("B")).toBe(false);
  });

  it("snapshots plain tags and resets everything", () => {
    const s = sim("XIC(A)OTE(B);\nXIC(A)TON(T1,100,0);");
    s.setInput("A", true);
    s.scan(50);
    s.scan(50);
    expect(s.snapshot()).toEqual({ A: true, B: true });
    expect(s.scanCount).toBe(2);
    s.reset();
    expect(s.snapshot()).toEqual({ A: false, B: false });
    expect(s.timer("T1")!.ACC).toBe(0);
    expect(s.scanCount).toBe(0);
  });

  it("lets a program write timer members through MOV", () => {
    const s = sim("XIC(PE)CTU(C1,10,0);\nXIC(Clr)MOV(0,C1.ACC);");
    s.setInput("PE", true);
    s.scan(0);
    expect(s.counter("C1")!.ACC).toBe(1);
    s.setInput("Clr", true);
    s.scan(0);
    expect(s.counter("C1")!.ACC).toBe(0);
  });
});
