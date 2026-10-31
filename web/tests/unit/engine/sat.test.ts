import { describe, expect, it } from "vitest";
import { parseProgram } from "../../../src/engine/parse";
import { analyzeExpr } from "../../../src/engine/sat";
import { E, buildXref } from "../../../src/engine/xref";

const condOf = (rung: string) => {
  const p = parseProgram(rung);
  expect(p.errors).toEqual([]);
  return buildXref(p.rungs).outputs[0].condition;
};

describe("satisfiability and tautology", () => {
  it.each([
    ["XIC(A)XIO(B)OTE(Y);", true, false],
    ["XIC(A)XIO(A)OTE(Y);", false, false],
    ["[XIC(A),XIO(A)]OTE(Y);", true, true],
    ["[XIC(A),]OTE(Y);", true, true],
    ["AFI()OTE(Y);", false, false],
    ["XIC(A)[XIO(A),XIC(B)XIO(B)]OTE(Y);", false, false],
    ["GRT(L,80)LES(L,50)OTE(Y);", false, false],
    ["GRT(L,50)LES(L,80)OTE(Y);", true, false],
    ["GEQ(L,5)LEQ(L,5)OTE(Y);", true, false],
    ["GRT(L,5)LEQ(L,5)OTE(Y);", false, false],
    ["EQU(L,3)EQU(L,4)OTE(Y);", false, false],
    ["EQU(L,3)NEQ(L,3)OTE(Y);", false, false],
    ["GEQ(L,5)LEQ(L,5)NEQ(L,5)OTE(Y);", false, false],
    ["LES(80,L)GRT(50,L)OTE(Y);", false, false],
    ["[GRT(L,10),LEQ(L,10)]OTE(Y);", true, true],
    ["EQU(L,3)GRT(L,1)OTE(Y);", true, false],
    ["EQU(L,3)GRT(L,5)OTE(Y);", false, false],
    ["LIM(10,L,20)GRT(L,50)OTE(Y);", false, false],
    ["P(A)XIO(A)OTE(Y);", true, false],
  ])("%s -> satisfiable %s, tautology %s", (rung, sat, taut) => {
    const r = analyzeExpr(condOf(rung));
    expect([r.satisfiable, r.tautology]).toEqual([sat, taut]);
  });

  it("gives up (null) beyond the variable budget", () => {
    const many = E.and(...Array.from({ length: 20 }, (_, i) => E.v(`T${i}`)));
    expect(analyzeExpr(many, 16)).toMatchObject({ satisfiable: null, tautology: null, atoms: 20 });
  });

  it("still decides constants without enumeration", () => {
    expect(analyzeExpr(E.t)).toMatchObject({ satisfiable: true, tautology: true, atoms: 0 });
    expect(analyzeExpr(E.f)).toMatchObject({ satisfiable: false, tautology: false, atoms: 0 });
  });
});
