// Differential test: the TypeScript parser must agree with the Python reference
// (contract/python/logiclens_ladder.py) on thousands of generated inputs.
// Skips cleanly when python3 is not installed.
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { iterInstructions, parseProgram, timerPresetMs } from "../../../src/engine/parse";

const CONTRACT_PY = path.resolve(__dirname, "../../../../contract/python");
const hasPython = spawnSync("python3", ["--version"]).status === 0;

const PY = `
import json, sys, math
sys.path.insert(0, sys.argv[1])
from logiclens_ladder import parse_program, iter_instructions, timer_preset_ms
def num(v):
    if v is None: return None
    if isinstance(v, float) and not math.isfinite(v): return str(v)
    return v
out = []
for text in json.load(open(sys.argv[2], encoding="utf-8")):
    try:
        r = parse_program(text)
    except Exception as e:
        out.append({"raises": type(e).__name__}); continue
    out.append({
      "ok": r.ok,
      "errors": [[e.code, e.line, e.col, e.message] for e in r.errors],
      "rungs": [{"number": x.number, "comment": x.comment, "line": x.line, "text": x.text,
                 "ins": [[i.id, i.mnemonic, i.index, i.col, num(timer_preset_ms(i)),
                          [[o.raw, o.type, num(o.value)] for o in i.operands]] for i in iter_instructions(x.body)]}
                for x in r.rungs],
    })
json.dump(out, sys.stdout, ensure_ascii=False)
`;

function tsView(text: string) {
  const r = parseProgram(text);
  const num = (v: number | null | undefined) =>
    v === undefined || v === null ? null : Number.isFinite(v) ? v : v > 0 ? "inf" : v < 0 ? "-inf" : "nan";
  return {
    ok: r.ok,
    errors: r.errors.map((e) => [e.code, e.line, e.col, e.message]),
    rungs: r.rungs.map((x) => ({
      number: x.number,
      comment: x.comment,
      line: x.line,
      text: x.text,
      ins: [...iterInstructions(x.body)].map((i) => [
        i.id,
        i.mnemonic,
        i.index,
        i.col,
        num(timerPresetMs(i)),
        i.operands.map((o) => [o.raw, o.type, num(o.value)]),
      ]),
    })),
  };
}

const pieces = [
  "XIC(A)", "XIO(B)", "OTE(C)", "OTL(L)", "OTU(L)", "[", "]", ",", ";", "(", ")", " ", "\t", "\n", "\r\n",
  "// c", "#n", "0003:", "Rung 2:", "N:", "N 4.", "TON(T1,5000,0)", "TON(T4:0,0.01,500,0)", "TON(T2,T#1m30s)",
  "CTU(C1,10,0)", "GRT(Level,80)", "LIM(10,T,20)", "MOV(16#FF,X)", "MOV(2#102,X)", "XIC(?)", "XIC(\"Motor Start\")",
  "XIC(%I0.0)", "XIC(Local:1:I.Data.0)", "XIC(Bits[3])", "JSR(S,1,2)", "MCR()", "AFI()", "foo(", "XIC A",
  "١٢:", "MOV(٣,Y)", "\u{1F600}", " ", " ", "\u0085", "\x1f", "ſ(L)", "XıC(A)",
  "XIC(A,B)", "TON(T,,0)", "T#5x", "1e400", "MOV(1e400,Z)", "NO(A)", "SET(X)", "r(Y)", "[]", "[,]",
];

describe.skipIf(!hasPython)("TypeScript parser == Python reference", () => {
  it("agrees on 3000 generated inputs plus the shared vectors", () => {
    const rng = fc.sample(
      fc.array(fc.constantFrom(...pieces), { minLength: 0, maxLength: 14 }).map((xs) => xs.join("")),
      { numRuns: 3000, seed: 20261031 },
    );
    // non-ASCII unit letters used to crash the Python reference (fixed with re.ASCII); keep them as regressions
    const formerPythonCrashes = ["XIC(A)TON(T1,T#5\u017f);", "XIC(A)TON(T1,T#5m\u017f);"];
    const inputs = [...rng, "", "\n\n", "XIC(A)OTE(B);\n".repeat(2003), ...formerPythonCrashes];
    const dir = mkdtempSync(path.join(tmpdir(), "llt-parity-"));
    try {
      const file = path.join(dir, "inputs.json");
      writeFileSync(file, JSON.stringify(inputs), "utf-8");
      const stdout = execFileSync("python3", ["-I", "-c", PY, CONTRACT_PY, file], {
        maxBuffer: 512 * 1024 * 1024,
        encoding: "utf-8",
      });
      const py = JSON.parse(stdout) as Array<Record<string, unknown>>;
      expect(py.length).toBe(inputs.length);
      let compared = 0;
      let withRungs = 0;
      let withErrors = 0;
      const pythonRaises: string[] = [];
      for (let k = 0; k < inputs.length; k++) {
        const theirs = py[k];
        if ("raises" in theirs) {
          pythonRaises.push(inputs[k]);
          continue;
        }
        const mine = tsView(inputs[k]);
        expect(mine, JSON.stringify(inputs[k])).toEqual(theirs);
        compared++;
        if (mine.rungs.length) withRungs++;
        if (mine.errors.length) withErrors++;
      }
      expect(compared).toBe(inputs.length);
      // the generated corpus must exercise both successful rungs and every kind of failure
      expect(withRungs).toBeGreaterThan(500);
      expect(withErrors).toBeGreaterThan(500);
      // the reference parser must never raise (contract: parsers return errors, never throw)
      expect(pythonRaises).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
