import { describe, expect, it } from "vitest";
import fc from "fast-check";
import cases from "../../../../contract/ladder_cases.json";
import {
  LIMITS,
  SPEC,
  classifyOperand,
  iterInstructions,
  parseProgram,
  printProgram,
  timeLiteralMs,
  timerPresetMs,
} from "../../../src/engine/parse";

type Case = {
  name: string;
  text: string;
  ok: boolean;
  errors?: string[];
  error_lines?: number[];
  rungs?: string[][];
  numbers?: number[];
  comments?: (string | null)[];
  canonical?: string;
  timer_preset_ms?: (number | null)[];
  operand_types?: string[];
};

const CASES = (cases as { cases: Case[] }).cases;

describe("shared contract vectors (contract/ladder_cases.json)", () => {
  it("has the vectors", () => {
    expect(CASES.length).toBeGreaterThanOrEqual(37);
  });

  for (const c of CASES) {
    it(c.name, () => {
      const res = parseProgram(c.text);
      expect(res.ok, JSON.stringify(res.errors)).toBe(c.ok);
      if (c.errors) expect(res.errors.map((e) => e.code)).toEqual(c.errors);
      if (c.error_lines) expect(res.errors.map((e) => e.line)).toEqual(c.error_lines);
      if (c.rungs) {
        expect(res.rungs.map((r) => [...iterInstructions(r.body)].map((i) => i.mnemonic))).toEqual(c.rungs);
      }
      if (c.numbers) expect(res.rungs.map((r) => r.number)).toEqual(c.numbers);
      if (c.comments) expect(res.rungs.map((r) => r.comment)).toEqual(c.comments);
      if (c.canonical !== undefined) expect(printProgram(res.rungs)).toBe(c.canonical);
      if (c.timer_preset_ms) {
        const got = res.rungs.flatMap((r) =>
          [...iterInstructions(r.body)]
            .filter((i) => ["TON", "TOF", "RTO", "TP"].includes(i.mnemonic))
            .map((i) => timerPresetMs(i)),
        );
        expect(got).toEqual(c.timer_preset_ms);
      }
      if (c.operand_types) {
        const got = res.rungs.flatMap((r) => [...iterInstructions(r.body)].flatMap((i) => i.operands.map((o) => o.type)));
        expect(got).toEqual(c.operand_types);
      }
    });
  }

  it("round-trips every valid case through the canonical printer", () => {
    for (const c of CASES) {
      const res = parseProgram(c.text);
      const again = parseProgram(printProgram(res.rungs));
      expect(again.errors, c.name).toEqual([]);
      expect(printProgram(again.rungs), c.name).toBe(printProgram(res.rungs));
    }
  });
});

describe("parser details mirrored from the Python reference", () => {
  it("assigns ids r{ordinal}i{index} in text order", () => {
    const res = parseProgram("XIC(A)[XIC(B),XIC(C)]OTE(D);\nXIC(E)OTE(F);");
    const ids = res.rungs.flatMap((r) => [...iterInstructions(r.body)].map((i) => i.id));
    expect(ids).toEqual(["r0i0", "r0i1", "r0i2", "r0i3", "r1i0", "r1i1"]);
  });

  it("keeps the canonical text on each rung", () => {
    const res = parseProgram("  xic( A ) ote(B) ");
    expect(res.rungs[0].text).toBe("XIC(A)OTE(B);");
  });

  it("points error columns at the problem (1-based, line relative)", () => {
    let res = parseProgram("XIC(A)FOO(B)OTE(C);");
    expect([res.errors[0].line, res.errors[0].col]).toEqual([1, 7]);
    res = parseProgram("0003: XIC(A)FOO(B);");
    expect(res.errors[0].col).toBe(13);
  });

  it("parses IEC time literals to milliseconds", () => {
    expect(timeLiteralMs("T#5s")).toBe(5000);
    expect(timeLiteralMs("t#1h2m3s4ms")).toBe(3_723_004);
    expect(timeLiteralMs("TIME#1.5s")).toBe(1500);
    expect(timeLiteralMs("T#1_000ms")).toBe(1000);
    expect(timeLiteralMs("T#-2s")).toBe(-2000);
    expect(timeLiteralMs("T#")).toBeNull();
    expect(timeLiteralMs("T#5x")).toBeNull();
    expect(timeLiteralMs("5s")).toBeNull();
  });

  it.each([
    ["?", "unknown"],
    ["12", "number"],
    ["-1.5", "number"],
    [".5", "number"],
    ["2e3", "number"],
    ["16#ff", "number"],
    ["8#17", "number"],
    ["2#1010", "number"],
    ["T#5s", "time"],
    ["I:1/0", "tag"],
    ["%MW10", "tag"],
    ['"Motor Start"', "tag"],
    ["Data[3].2", "tag"],
  ])("classifies %s as %s", (raw, type) => {
    expect(classifyOperand(raw)?.type).toBe(type);
  });

  it("gives radix literals their value", () => {
    expect(classifyOperand("16#FF")?.value).toBe(255);
    expect(classifyOperand("2#1_01")?.value).toBe(5);
    expect(classifyOperand("8#17")?.value).toBe(15);
  });

  it.each(["Start PB", "a+b", "x;y", "'q'", "16#XYZ", "2#102", 'bad"quote', "", "\x01", "16#__"])(
    "rejects invalid operand %j",
    (raw) => {
      expect(classifyOperand(raw)).toBeNull();
    },
  );

  it("accepts Unicode decimal digits where Python's \\d does", () => {
    const res = parseProgram("١٢: XIC(A)OTE(B);\nMOV(٣,X);");
    expect(res.errors).toEqual([]);
    expect(res.rungs.map((r) => r.number)).toEqual([12, 13]);
    expect(res.rungs[1].body.items[0]).toMatchObject({ operands: [{ type: "number", value: 3 }, { type: "tag" }] });
  });

  it("treats a non-ASCII time unit as an invalid operand instead of crashing", () => {
    const res = parseProgram("XIC(A)TON(T1,T#5ſ);");
    expect(res.errors.map((e) => e.code)).toEqual(["E_SYNTAX"]);
  });

  it("counts code points, not UTF-16 units, for columns", () => {
    const res = parseProgram('XIC("\u{1F600}x")FOO(B);');
    expect(res.errors[0].col).toBe(10); // Python: len() counts the emoji once
  });

  it("splits lines like Python splitlines()", () => {
    const res = parseProgram("XIC(A)OTE(B);\rXIC(C)OTE(D); XIC(E)OTE(F);\u0085FOO(X);");
    expect(res.rungs.map((r) => r.line)).toEqual([1, 2, 3]);
    expect(res.errors.map((e) => e.line)).toEqual([4]);
  });

  it("enforces the program size limit", () => {
    const res = parseProgram("XIC(A)OTE(B);\n".repeat(Math.floor(LIMITS.program_chars / 14) + 1));
    expect(res.errors.map((e) => e.code)).toEqual(["E_LIMIT"]);
    expect(res.rungs).toEqual([]);
  });

  it("enforces the rung count limit and still assigns ids", () => {
    const res = parseProgram("XIC(A)OTE(B);\n".repeat(LIMITS.rungs + 5));
    expect(res.rungs.length).toBe(LIMITS.rungs);
    expect(res.errors.at(-1)?.code).toBe("E_LIMIT");
    expect(res.rungs[0].body.items[0]).toMatchObject({ id: "r0i0" });
  });

  it("enforces the instruction count limit", () => {
    const res = parseProgram("XIC(A)".repeat(LIMITS.instructions) + "OTE(B);");
    expect(res.errors.map((e) => e.code)).toEqual(["E_LIMIT"]);
  });

  it("enforces the rung length limit", () => {
    const res = parseProgram("XIC(A)".repeat(700) + "OTE(B);");
    expect(res.errors.map((e) => e.code)).toEqual(["E_LIMIT"]);
  });

  it("does not throw on non-string input", () => {
    // @ts-expect-error deliberate bad input
    expect(parseProgram(null).errors[0].code).toBe("E_SYNTAX");
  });

  it("exposes the instruction table", () => {
    expect(SPEC.TON).toEqual([2, 4, "out"]);
    expect(SPEC.XIC[2]).toBe("in");
  });

  it("computes SLC timer presets with Python's round(x, 6)", () => {
    const res = parseProgram("XIC(A)TON(T4:0,0.001,7.8125,0);");
    const ton = [...iterInstructions(res.rungs[0].body)][1];
    expect(timerPresetMs(ton)).toBe(7.8125);
    const res2 = parseProgram("XIC(A)TON(T4:0,0.0078125,0.001,0);");
    expect(timerPresetMs([...iterInstructions(res2.rungs[0].body)][1])).toBe(0.007812);
  });
});

// ---------------------------------------------------------------- properties
const tagArb = fc
  .tuple(fc.constantFrom("A", "B", "Start_PB", "I:1/0", "%Q0.1", "T1.DN", "Data[2]", "Local:1:I.Data.0"), fc.integer({ min: 0, max: 9 }))
  .map(([t, n]) => `${t}${n}`);
const inputArb = fc.oneof(
  tagArb.map((t) => `XIC(${t})`),
  tagArb.map((t) => `XIO(${t})`),
  fc.tuple(tagArb, fc.integer({ min: -50, max: 999 })).map(([t, n]) => `GRT(${t},${n})`),
  tagArb.map((t) => `ONS(${t})`),
);
const outputArb = fc.oneof(
  tagArb.map((t) => `OTE(${t})`),
  tagArb.map((t) => `OTL(${t})`),
  fc.tuple(tagArb, fc.integer({ min: 0, max: 99999 })).map(([t, n]) => `TON(${t},${n},0)`),
  fc.tuple(fc.integer({ min: 0, max: 9 }), tagArb).map(([n, t]) => `MOV(${n},${t})`),
);
const seqArb: fc.Arbitrary<string> = fc.letrec((tie) => ({
  seq: fc.array(fc.oneof({ depthSize: "small", withCrossShrink: true }, inputArb, tie("branch")), { minLength: 1, maxLength: 4 }).map((xs) => xs.join("")),
  branch: fc.array(tie("seq"), { minLength: 2, maxLength: 3 }).map((legs) => `[${legs.join(",")}]`),
})).seq as fc.Arbitrary<string>;
const rungArb = fc.tuple(seqArb, outputArb).map(([s, o]) => `${s}${o};`);

describe("parser properties", () => {
  it("prints exactly what it parsed for generated canonical programs", () => {
    fc.assert(
      fc.property(fc.array(rungArb, { minLength: 1, maxLength: 5 }), (rungs) => {
        const text = rungs.join("\n");
        const res = parseProgram(text);
        if (res.errors.length) return res.errors.every((e) => e.code === "E_LIMIT");
        return printProgram(res.rungs) === text;
      }),
      { numRuns: 400 },
    );
  });

  it("never throws on arbitrary text and always returns well-formed errors", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 120, unit: fc.constantFrom(..."XIC()[],;/#:.?\"T5s \n\tabcxyzOTE01-+_%".split("")) }), (text) => {
        const res = parseProgram(text);
        return Array.isArray(res.errors) && res.errors.every((e) => typeof e.code === "string" && e.line >= 0 && e.col >= 0);
      }),
      { numRuns: 2000 },
    );
  });

  it("never throws on arbitrary unicode", () => {
    fc.assert(
      fc.property(fc.string({ maxLength: 60, unit: "grapheme" }), (text) => {
        parseProgram(text);
        return true;
      }),
      { numRuns: 500 },
    );
  });
});
