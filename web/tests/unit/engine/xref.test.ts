import { describe, expect, it } from "vitest";
import { parseProgram } from "../../../src/engine/parse";
import { E, buildXref, exprToString } from "../../../src/engine/xref";
import { tagKey } from "../../../src/engine/tags";

const xrefOf = (text: string) => {
  const p = parseProgram(text);
  expect(p.errors).toEqual([]);
  return buildXref(p.rungs);
};

describe("expression constructors", () => {
  it("simplifies constants and flattens", () => {
    const a = E.v("A");
    const b = E.v("B");
    expect(E.and()).toEqual(E.t);
    expect(E.or()).toEqual(E.f);
    expect(E.and(a, E.t)).toEqual(a);
    expect(E.and(a, E.f)).toEqual(E.f);
    expect(E.or(a, E.t)).toEqual(E.t);
    expect(E.or(a, E.f)).toEqual(a);
    expect(E.not(E.not(a))).toEqual(a);
    expect(E.not(E.t)).toEqual(E.f);
    expect(E.and(E.and(a, b), a)).toEqual({ op: "and", args: [a, b, a] });
  });
});

describe("rung-condition walk (Logix semantics)", () => {
  it("gives the seal-in output its readable condition", () => {
    const x = xrefOf("XIC(Start_PB)[XIC(Motor_Run),XIC(Remote_Start)]XIO(Stop_PB)OTE(Motor_Run);");
    const out = x.outputs[0];
    expect(out.target).toBe(tagKey("Motor_Run"));
    expect(out.text).toBe("Start_PB AND (Motor_Run OR Remote_Start) AND NOT Stop_PB");
  });

  it("passes power through outputs so mid-rung outputs see a prefix", () => {
    const x = xrefOf("XIC(A)OTE(B)XIC(C)OTE(D);");
    expect(x.outputs.map((o) => o.text)).toEqual(["A", "A AND C"]);
  });

  it("gives every parallel output the same condition", () => {
    const x = xrefOf("XIC(A)[OTE(B),XIO(C)OTE(D)];");
    expect(x.outputs.map((o) => [o.mnemonic, o.text])).toEqual([
      ["OTE", "A"],
      ["OTE", "A AND NOT C"],
    ]);
  });

  it("treats an empty leg as a wire", () => {
    const x = xrefOf("[XIC(A),]OTE(B);");
    expect(x.outputs[0].condition).toEqual(E.t);
    expect(x.outputs[0].text).toBe("TRUE");
  });

  it("renders compares, limits, edges and one-shots", () => {
    const x = xrefOf("GRT(Level,80)LIM(10,Temp,20)P(Sensor)ONS(OS1)EQU(Mode,2)NEQ(A,B)GEQ(C,1)LEQ(D,2)LES(E1,3)N(F)OTE(Out);");
    expect(x.outputs[0].text).toBe(
      "(Level > 80) AND (10 <= Temp <= 20) AND RISING(Sensor) AND ONESHOT(OS1) AND (Mode = 2) AND (A <> B) AND (C >= 1) AND (D <= 2) AND (E1 < 3) AND FALLING(F)",
    );
  });

  it("folds constant compares and AFI", () => {
    const x = xrefOf("GRT(5,3)OTE(A);\nLES(5,3)OTE(B);\nEQU(X,X)OTE(C);\nAFI()OTE(D);\nLBL(L1)OTE(E);");
    expect(x.outputs.map((o) => o.text)).toEqual(["TRUE", "FALSE", "TRUE", "FALSE", "TRUE"]);
  });

  it("wraps OR inside AND and AND inside OR with parentheses", () => {
    const x = xrefOf("[XIC(A)XIC(B),XIC(C)][XIC(D),XIC(E)]OTE(F);");
    expect(x.outputs[0].text).toBe("((A AND B) OR C) AND (D OR E)");
    const y = xrefOf("[XIO(A),XIC(B)]XIO(C)OTE(F);\n[[XIC(A),XIC(B)]XIC(C),XIC(D)]OTE(G);");
    expect(y.outputs.map((o) => o.text)).toEqual(["(NOT A OR B) AND NOT C", "((A OR B) AND C) OR D"]);
  });

  it("negates compound expressions with parentheses", () => {
    expect(exprToString(E.not(E.and(E.v("A"), E.v("B"))))).toBe("NOT (A AND B)");
  });
});

describe("cross reference", () => {
  const x = xrefOf(
    "XIC(Start)[XIC(Motor),]XIO(Stop)OTE(Motor);\nXIC(Motor)TON(T1,5000,0);\nXIC(T1.DN)OTE(Lamp);\nGRT(Level,80)ADD(Count,1,Count)MOV(Count,N7:0);\nXIC(Skip)JMP(L1);\nLBL(L1)JSR(Sub1,P1);",
  );

  it("records reads and writes with rung numbers and instruction ids", () => {
    const motor = x.tags.get(tagKey("Motor"))!;
    expect(motor.reads.map((r) => [r.rung, r.instrId, r.mnemonic])).toEqual([
      [0, "r0i1", "XIC"],
      [1, "r1i0", "XIC"],
    ]);
    expect(motor.writes.map((r) => [r.rung, r.mnemonic])).toEqual([[0, "OTE"]]);
    const count = x.tags.get(tagKey("Count"))!;
    expect(count.reads.map((r) => r.mnemonic)).toEqual(["ADD", "MOV"]);
    expect(count.writes.map((r) => r.mnemonic)).toEqual(["ADD"]);
  });

  it("links member reads to timer instances", () => {
    const dn = x.tags.get(tagKey("T1.DN"))!;
    expect(dn.memberOf).toBe(tagKey("T1"));
    expect(x.tags.get(tagKey("T1"))!.instance).toBe("timer");
    expect(x.instances.get(tagKey("T1"))!.mnemonics).toEqual(["TON"]);
  });

  it("keeps labels and routines out of the tag table", () => {
    expect(x.tags.has(tagKey("L1"))).toBe(false);
    expect(x.tags.has(tagKey("Sub1"))).toBe(false);
    expect(x.labels.get(tagKey("L1"))).toMatchObject({ lbl: [{ rung: 5, instrId: "r5i0" }], jmp: [{ rung: 4, instrId: "r4i1" }] });
    expect(x.routines).toEqual(["Sub1"]);
    expect(x.tags.get(tagKey("P1"))!.reads).toHaveLength(1);
  });

  it("builds condition and data dependencies", () => {
    expect(x.dependencies).toContainEqual(expect.objectContaining({ from: tagKey("Start"), to: tagKey("Motor"), kind: "condition" }));
    expect(x.dependencies).toContainEqual(expect.objectContaining({ from: tagKey("Level"), to: tagKey("Count"), kind: "condition" }));
    expect(x.dependencies).toContainEqual(expect.objectContaining({ from: tagKey("Count"), to: tagKey("N7:0"), kind: "data" }));
    expect(x.dependencies).toContainEqual(expect.objectContaining({ from: tagKey("T1.DN"), to: tagKey("Lamp"), kind: "condition" }));
  });

  it("classifies tags", () => {
    expect(x.tags.get(tagKey("N7:0"))!.physical).toBe("internal");
    expect(x.tags.get(tagKey("Stop"))!.hints).toContain("stop");
  });
});

describe("scan-order notes", () => {
  it("notes a bit read before the rung that writes it", () => {
    const x = xrefOf("XIC(Aux)OTE(Lamp);\nXIC(Start)OTE(Aux);");
    expect(x.scanNotes).toEqual([
      expect.objectContaining({ tag: tagKey("Aux"), readRung: 0, writeRung: 1 }),
    ]);
  });

  it("does not note a seal-in or a bit written earlier", () => {
    const x = xrefOf("XIC(Start)[XIC(Motor),]OTE(Motor);\nXIC(Motor)OTE(Lamp);");
    expect(x.scanNotes).toEqual([]);
  });

  it("notes timer members read before their timer", () => {
    const x = xrefOf("XIC(T1.DN)OTE(Lamp);\nXIC(A)TON(T1,100,0);");
    expect(x.scanNotes.map((n) => n.tag)).toEqual([tagKey("T1.DN")]);
  });

  it("ignores pure inputs", () => {
    const x = xrefOf("XIC(I:1/0)OTE(O:2/0);");
    expect(x.scanNotes).toEqual([]);
  });
});
