import { describe, expect, it } from "vitest";
import { parseProgram } from "../../../src/engine/parse";
import { commentSafe, sanitizeIdentifier, toStructuredText } from "../../../src/engine/st";
import { tagKey } from "../../../src/engine/tags";
import { StInterpreter } from "../../helpers/st-interpreter";

const st = (text: string, opts = {}) => {
  const p = parseProgram(text);
  expect(p.errors).toEqual([]);
  return toStructuredText(p.rungs, opts);
};
const lines = (code: string) => code.split("\n").map((l) => l.trim());

describe("identifiers and comments", () => {
  it.each([
    ["Start_PB", "Start_PB"],
    ["I:1/0", "I_1_0"],
    ["%I0.0", "I0_0"],
    ["Local:1:I.Data.0", "Local_1_I_Data_0"],
    ['"Motor Start"', "Motor_Start"],
    ["3:0/1", "X_3_0_1"],
    ["A__B_", "A_B"],
    ["IF", "IF_TAG"],
    ["ton", "ton_TAG"],
    ["Bits[3]", "Bits_3"],
    ["___", "TAG"],
  ])("%s -> %s", (raw, id) => {
    expect(sanitizeIdentifier(raw)).toBe(id);
  });

  it("neutralises comment terminators", () => {
    for (const evil of ["x *) Danger := TRUE; (* y", "(*)", "a */ b /* c", "**)**", "//x"]) {
      const s = commentSafe(evil);
      expect(s).not.toMatch(/\(\*|\*\)|\/\*|\*\/|\/\//);
    }
  });

  it("cannot be broken out of by a quoted tag (injection)", () => {
    // balanced parentheses keep this a single valid quoted tag for the LLT parser
    const res = st('XIC("(*x*) Danger := TRUE; (*y*)")OTE(Out);');
    // every comment closes on its own line and no extra statement appears
    for (const l of res.code.split("\n")) {
      const opens = l.split("(*").length - 1;
      const closes = l.split("*)").length - 1;
      expect(opens).toBe(closes);
    }
    expect(res.code).not.toMatch(/^\s*Danger\s*:=/m);
    new StInterpreter(res.code); // still parses
  });

  it("keeps identifiers unique case-insensitively", () => {
    const res = st("XIC(A.B)XIC(A_B)XIC(a_b)OTE(Out);");
    const ids = [res.identifiers[tagKey("A.B")], res.identifiers[tagKey("A_B")]];
    expect(new Set(ids.map((x) => x.toUpperCase())).size).toBe(2);
  });
});

describe("rung translation", () => {
  it("translates a seal-in rung to one assignment with the factored condition", () => {
    const res = st("// Motor\n[XIC(Start_PB),XIC(Motor)]XIC(Stop_PB)OTE(Motor);");
    expect(lines(res.code)).toContain("Motor := (Start_PB OR Motor) AND Stop_PB;");
    expect(res.code).toContain("(* Rung 0: Motor *)");
    expect(res.code).toMatch(/Start_PB\s+: BOOL;/);
  });

  it("uses XIO as NOT and NCOIL as a negated assignment", () => {
    const res = st("XIC(A)XIO(B)NCOIL(C);");
    expect(lines(res.code)).toContain("C := NOT (A AND NOT B);");
  });

  it("latches through IF and keeps unconditional latches flat", () => {
    const res = st("XIC(A)OTL(L);\nOTU(L);");
    expect(lines(res.code)).toEqual(expect.arrayContaining(["IF A THEN", "L := TRUE;", "END_IF;", "L := FALSE;"]));
  });

  it("calls each timer once with its preset in every syntax", () => {
    const res = st("XIC(A)TON(T1,5000,0);\nXIC(B)TON(T4:0,0.01,250,0);\nXIC(C)TOF(T2,T#1m30s);\nXIC(D)TP(T3,1500);\nXIC(E)TON(T5,Pre,0);");
    const l = lines(res.code);
    expect(l).toContain("T1(IN := A, PT := T#5s);");
    expect(l).toContain("T4_0(IN := B, PT := T#2500ms);");
    expect(l).toContain("T2(IN := C, PT := T#90s);");
    expect(l).toContain("T3(IN := D, PT := T#1500ms);");
    expect(res.code).toMatch(/T5\(IN := E, PT := DINT_TO_TIME\(TRUNC\(Pre\)\)\);/);
    expect(res.instanceTypes).toMatchObject({ T1: "TON", T2: "TOF", T3: "TP" });
  });

  it("maps timer and counter members", () => {
    const res = st("XIC(A)TON(T1,100,0);\nXIC(T1.DN)XIO(T1.TT)GRT(T1.ACC,50)OTE(X);\nXIC(B)CTU(C1,3,0);\nXIC(C1.DN)LES(C1.ACC,2)OTE(Y);\nXIC(C)CTD(C2,0);\nXIC(C2.DN)OTE(Z);");
    const l = lines(res.code);
    expect(l).toContain("X := T1.Q AND NOT (T1.IN AND NOT T1.Q) AND (TIME_TO_DINT(T1.ET) > 50);");
    expect(l).toContain("Y := C1.Q AND (C1.CV < 2);");
    expect(l).toContain("Z := C2.QU;");
    expect(l.some((x) => x.startsWith("C2(CU := FALSE, CD := C, R := FALSE, PV := 0);"))).toBe(true);
  });

  it("feeds RES through a gating BOOL instead of a second call", () => {
    const res = st("XIC(A)TON(T1,100,0);\nXIC(R)RES(T1);\nXIC(B)CTU(C1,3,0);\nXIC(R)RES(C1);");
    const l = lines(res.code);
    expect(l.filter((x) => x.startsWith("T1(")).length).toBe(1);
    expect(l.some((x) => x.startsWith("T1(IN := A AND NOT T1_RST, PT := T#100ms);"))).toBe(true);
    expect(l).toContain("T1_RST := R;");
    expect(l).toContain("C1(CU := B, R := C1_RST, PV := 3);");
  });

  it("merges a Rockwell CTU + CTD pair into one CTUD call", () => {
    const res = st("XIC(In)CTU(C1,10,0);\nXIC(Out)CTD(C1,10,0);");
    const l = lines(res.code);
    expect(l).toContain("C1_CU := In;");
    expect(l).toContain("C1_CD := Out;");
    expect(l.filter((x) => x.startsWith("C1(")).length).toBe(1);
  });

  it("translates a reused timer only once and warns", () => {
    const res = st("XIC(A)TON(T1,100,0);\nXIC(B)TON(T1,100,0);");
    expect(lines(res.code).filter((x) => x.startsWith("T1(")).length).toBe(1);
    expect(res.warnings.join(" ")).toMatch(/more than one timer instruction/);
  });

  it("translates edges and one-shots with R_TRIG / F_TRIG", () => {
    const res = st("P(A)OTE(X);\nN(A)OTE(Y);\nXIC(B)ONS(S1)OTE(Z);\nXIC(C)OSR(S2,W);\nXIC(C)OSF(S3,V);");
    expect(res.code).toMatch(/RT_r0i0\s+: R_TRIG;/);
    expect(res.code).toMatch(/FT_r1i0\s+: F_TRIG;/);
    const l = lines(res.code);
    expect(l).toContain("RT_r0i0(CLK := A);");
    expect(l).toContain("X := RT_r0i0.Q;");
    expect(l).toContain("ONS_r2i1(CLK := B);");
    expect(l).toContain("Z := B AND ONS_r2i1.Q;");
    expect(l).toContain("OSR_r3i1(CLK := C);");
    expect(l).toContain("W := OSR_r3i1.Q;");
  });

  it("translates math, moves, bitwise ops and guards variable divisors", () => {
    const res = st("XIC(A)ADD(N7:0,1,N7:0);\nMOV(2.5,Level);\nXIC(B)DIV(Level,Div,Out);\nXIC(C)AND(W1,6,W2);\nMOV(Level,N7:1);");
    const l = lines(res.code);
    expect(l).toContain("N7_0 := (N7_0 + 1);");
    expect(l).toContain("Level := 2.5;");
    expect(l).toEqual(expect.arrayContaining(["IF Div <> 0.0 THEN", "Out := (Level / Div);", "Out := 0.0;"]));
    expect(l).toContain("W2 := (W1 AND 6);");
    expect(l).toContain("N7_1 := TRUNC(Level);");
  });

  it("expands circular LIM", () => {
    expect(lines(st("LIM(20,T,10)OTE(Y);").code)).toContain("Y := ((T >= 20.0) OR (T <= 10.0));");
  });

  it("uses temporaries only when a rung writes something it reads later", () => {
    expect(st("XIC(A)OTE(B);").code).not.toMatch(/RC_/);
    const res = st("XIC(A)XIO(B)OTE(B)XIC(C)OTE(D);");
    expect(res.code).toMatch(/RC_0_1 := A;/);
    expect(res.code).toMatch(/RC_0_2 := RC_0_1 AND NOT B;/);
    expect(lines(res.code)).toContain("B := RC_0_2;");
    expect(lines(res.code)).toContain("D := RC_0_3;");
  });

  it("wraps forward jumps and MCR zones and stops at END", () => {
    const res = st("XIC(Skip)JMP(L1);\nXIC(A)OTE(B);\nLBL(L1)XIC(A)OTE(C);\nXIC(Z)MCR();\nXIC(A)OTE(D);\nMCR();\nEND();\nXIC(A)OTE(E);");
    const l = lines(res.code);
    expect(l).toContain("JMP_L1_0 := FALSE;");
    expect(l).toContain("JMP_L1_0 := Skip;");
    expect(l).toContain("IF NOT (JMP_L1_0) THEN");
    expect(l).toContain("MCR_3 := Z;");
    expect(l).toEqual(expect.arrayContaining(["IF MCR_3 THEN", "D := A;", "ELSE", "D := FALSE;"]));
    expect(res.code).toMatch(/END in rung 6: 1 rung\(s\) after it are not translated/);
    expect(res.code).not.toMatch(/\bE := A/);
  });

  it("comments out backward jumps, missing labels and JSR with warnings", () => {
    const res = st("LBL(Top)XIC(A)OTE(B);\nXIC(C)JMP(Top);\nXIC(D)JMP(Nope);\nXIC(E)JSR(Sub1,P);");
    expect(res.warnings.join(" ")).toMatch(/backward/);
    expect(res.warnings.join(" ")).toMatch(/missing its label/);
    expect(res.warnings.join(" ")).toMatch(/JSR\(Sub1\)/);
    new StInterpreter(res.code);
  });

  it("is deterministic and prints generatedAt only when given", () => {
    const t = "XIC(A)OTE(B);";
    expect(st(t).code).toBe(st(t).code);
    expect(st(t).code).not.toMatch(/Generated/);
    expect(st(t, { generatedAt: "2026-10-31" }).code).toMatch(/Generated 2026-10-31/);
  });
});

describe("generated code runs", () => {
  it("behaves like the ladder on the seal-in circuit", () => {
    const res = st("[XIC(Start_PB),XIC(Motor)]XIC(Stop_PB)OTE(Motor);");
    const vm = new StInterpreter(res.code);
    vm.set("Stop_PB", true);
    vm.set("Start_PB", true);
    vm.scan(10);
    vm.set("Start_PB", false);
    vm.scan(10);
    expect(vm.get("Motor")).toBe(true);
    vm.set("Stop_PB", false);
    vm.scan(10);
    expect(vm.get("Motor")).toBe(false);
  });

  it("declares every identifier validly and balances IF/END_IF", () => {
    const res = st("XIC(I:1/0)XIO(%I0.1)[XIC(Local:1:I.Data.0),XIC(\"A B\")]TON(T4:0,0.01,500,0);\nXIC(T4:0/DN)CTU(C5:0,3,0);\nXIC(C5:0/DN)OTL(O:2/0);");
    const decl = res.code.split("\n").filter((l) => /^\s{2}\S+\s+: /.test(l)).map((l) => l.trim().split(/\s+/)[0]);
    for (const d of decl) {
      expect(d).toMatch(/^[A-Za-z][A-Za-z0-9_]*$/);
      expect(d).not.toMatch(/__|_$/);
    }
    const l = lines(res.code);
    expect(l.filter((x) => x.startsWith("IF ")).length).toBe(l.filter((x) => x === "END_IF;").length);
  });
});

describe("unread operands", () => {
  it("never translates a ? silently: header warning, warning list and an inline marker on the preset", () => {
    const { code, warnings } = toStructuredText(parseProgram("XIC(A)TON(T1,?,0);\nXIC(?)OTE(B);").rungs);
    expect(warnings[0]).toMatch(/Unread operands/);
    expect(code).toMatch(/WARNING: unread operands/);
    expect(code).toContain("PT := T#0ms (* ? unread preset *)");
  });

  it("adds no warning when every operand was read", () => {
    const { code, warnings } = toStructuredText(parseProgram("XIC(A)TON(T1,500,0);").rungs);
    expect(warnings.join(" ")).not.toMatch(/Unread/);
    expect(code).not.toMatch(/WARNING: unread/);
  });
});
