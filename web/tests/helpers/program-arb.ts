// fast-check arbitraries producing valid LogicLens Ladder Text programs.
//
// `programArb({ differential: true })` restricts itself to constructs the Structured Text
// generator translates exactly (no RES/JMP/LBL/MCR/JSR/END, every timer/counter instance used
// by one instruction), so the simulator and the ST interpreter must agree on it.

import fc from "fast-check";

export interface ProgramArbOptions {
  differential?: boolean;
  maxRungs?: number;
}

const bitTag = fc.constantFrom("I1", "I2", "I3", "I4", "B1", "B2", "B3", "Out1", "Out2");
const memberTag = fc.constantFrom("T1.DN", "T2.DN", "T1.TT", "T2.EN", "T3.DN", "C1.DN", "C2.DN");
const contactTag = fc.oneof({ weight: 5, arbitrary: bitTag }, { weight: 1, arbitrary: memberTag });
const numTag = fc.constantFrom("NI1", "NI2", "N1", "N2", "T1.ACC", "C1.ACC");
const lit = fc.oneof({ weight: 3, arbitrary: fc.integer({ min: -3, max: 30 }).map(String) }, { weight: 1, arbitrary: fc.constantFrom("0.5", "2.5", "100") });
const cmpM = fc.constantFrom("EQU", "NEQ", "GRT", "GEQ", "LES", "LEQ");
const coilTag = fc.constantFrom("B1", "B2", "B3", "Out1", "Out2");

const inputArb = fc.oneof(
  { weight: 6, arbitrary: contactTag.map((t) => `XIC(${t})`) },
  { weight: 3, arbitrary: contactTag.map((t) => `XIO(${t})`) },
  { weight: 2, arbitrary: fc.tuple(cmpM, numTag, fc.oneof(numTag, lit)).map(([m, a, b]) => `${m}(${a},${b})`) },
  { weight: 1, arbitrary: fc.tuple(lit, numTag, lit).map(([a, t, b]) => `LIM(${a},${t},${b})`) },
  { weight: 1, arbitrary: bitTag.map((t) => `P(${t})`) },
  { weight: 1, arbitrary: bitTag.map((t) => `N(${t})`) },
  { weight: 1, arbitrary: fc.constant("ONS(@S)") },
);

const outputArb = fc.oneof(
  { weight: 8, arbitrary: coilTag.map((t) => `OTE(${t})`) },
  { weight: 2, arbitrary: coilTag.map((t) => `OTL(${t})`) },
  { weight: 2, arbitrary: coilTag.map((t) => `OTU(${t})`) },
  { weight: 1, arbitrary: coilTag.map((t) => `NCOIL(${t})`) },
  { weight: 1, arbitrary: coilTag.map((t) => `OSR(@S,${t})`) },
  { weight: 1, arbitrary: coilTag.map((t) => `OSF(@S,${t})`) },
  {
    weight: 3,
    arbitrary: fc
      .tuple(fc.constantFrom("TON", "TOF", "TP", "RTO"), fc.constantFrom("0", "100", "250", "1000", "T#300ms"))
      .map(([m, p]) => (m === "TP" ? `TP(@T,${p})` : `${m}(@T,${p},0)`)),
  },
  {
    weight: 2,
    arbitrary: fc
      .tuple(fc.constantFrom("CTU", "CTD", "CTUD"), fc.integer({ min: -1, max: 5 }))
      .map(([m, p]) => (m === "CTUD" ? `CTUD(@C,${p},I2)` : `${m}(@C,${p},0)`)),
  },
  {
    weight: 2,
    arbitrary: fc
      .tuple(fc.constantFrom("ADD", "SUB", "MUL", "DIV"), fc.oneof(numTag, lit), fc.oneof(numTag, lit), fc.constantFrom("N1", "N2", "N3"))
      .map(([m, a, b, d]) => `${m}(${a},${b},${d})`),
  },
  { weight: 1, arbitrary: fc.tuple(fc.oneof(numTag, lit), fc.constantFrom("N1", "N2", "N3")).map(([a, d]) => `MOV(${a},${d})`) },
  {
    weight: 1,
    arbitrary: fc.tuple(fc.constantFrom("AND", "OR", "XOR"), fc.constantFrom("W1", "W2", "NI1", "7"), fc.constantFrom("W1", "W2", "3")).map(([m, a, b]) => `${m}(${a},${b},W3)`),
  },
  { weight: 1, arbitrary: fc.constantFrom("W1", "W2", "5").map((a) => `NOT(${a},W4)`) },
);

const controlArb = fc.constantFrom(
  "RES(T1)",
  "RES(C1)",
  "JSR(Sub1)",
  "NOP()",
  "JMP(L1)",
  "JMP(L2)",
  "MCR()",
  "TON(T1,100,0)",
  "CTU(C1,2,0)",
  "OTE(?)",
);

function seqArb(diff: boolean): fc.Arbitrary<string> {
  const { seq } = fc.letrec<{ seq: string; branch: string }>((tie) => ({
    seq: fc
      .array(
        fc.oneof(
          { maxDepth: 3, depthSize: "small" },
          { weight: 5, arbitrary: inputArb },
          { weight: 1, arbitrary: tie("branch") },
          { weight: 1, arbitrary: diff ? outputArb : fc.oneof(outputArb, controlArb) },
        ),
        { minLength: 1, maxLength: 4 },
      )
      .map((xs) => xs.join("")),
    branch: fc
      .array(fc.oneof({ weight: 5, arbitrary: tie("seq") }, { weight: 1, arbitrary: fc.constant("") }), { minLength: 2, maxLength: 3 })
      .map((legs) => `[${legs.join(",")}]`),
  }));
  return seq;
}

function rungArb(diff: boolean): fc.Arbitrary<string> {
  const outs = fc.oneof(
    { weight: 4, arbitrary: diff ? outputArb : fc.oneof({ weight: 6, arbitrary: outputArb }, { weight: 1, arbitrary: controlArb }) },
    { weight: 1, arbitrary: fc.tuple(outputArb, outputArb).map(([a, b]) => `[${a},${b}]`) },
  );
  const label = diff ? fc.constant("") : fc.constantFrom("", "", "", "", "LBL(L1)", "LBL(L2)");
  return fc.tuple(label, seqArb(diff), outs, fc.boolean()).map(([l, s, o, c]) => `${c ? "// generated rung\n" : ""}${l}${s}${o};`);
}

/** Replace placeholders: @S -> unique one-shot storage, @T / @C -> timer / counter instances. */
export function finalize(text: string): string {
  let s = 0;
  let t = 0;
  let c = 0;
  return text
    .replace(/@S/g, () => `S${++s}`)
    .replace(/@T/g, () => (++t <= 3 ? `T${t}` : `TX${t}`))
    .replace(/@C/g, () => (++c <= 2 ? `C${c}` : `CX${c}`));
}

export function programArb(opts: ProgramArbOptions = {}): fc.Arbitrary<string> {
  const diff = !!opts.differential;
  return fc.array(rungArb(diff), { minLength: 1, maxLength: opts.maxRungs ?? 8 }).map((rs) => finalize(rs.join("\n")));
}

/** Random value for an input of a given data type. */
export function inputValueArb(type: string | undefined): fc.Arbitrary<boolean | number> {
  if (type === "DINT") return fc.integer({ min: -5, max: 40 });
  if (type === "REAL") return fc.oneof(fc.integer({ min: -5, max: 40 }), fc.constantFrom(0.5, 2.25, 99.5));
  return fc.boolean();
}
