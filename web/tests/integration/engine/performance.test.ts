// (e) A 2000-rung program must analyse in well under 1.5 s.
import { describe, expect, it } from "vitest";
import { analyzeProgram, createSimulator } from "../../../src/engine";

function bigProgram(rungs: number): string {
  const out: string[] = [];
  for (let i = 0; i < rungs; i++) {
    const n = i % 8;
    const t = `Area${Math.floor(i / 8)}`;
    if (n === 0) out.push(`// ${t} motor`, `[XIC(${t}_Start_PB),XIC(${t}_Motor)]XIC(${t}_Stop_PB)XIO(${t}_OL)OTE(${t}_Motor);`);
    else if (n === 1) out.push(`XIC(${t}_Motor)TON(${t}_Tmr,5000,0);`);
    else if (n === 2) out.push(`XIC(${t}_Tmr.DN)XIC(${t}_PE)ONS(${t}_OS)CTU(${t}_Cnt,10,0);`);
    else if (n === 3) out.push(`XIC(${t}_Reset)RES(${t}_Cnt);`);
    else if (n === 4) out.push(`GRT(${t}_Level,80)LES(${t}_Level,95)[XIC(${t}_Auto),XIC(${t}_Man)]OTE(${t}_Pump);`);
    else if (n === 5) out.push(`XIC(${t}_Cnt.DN)ADD(${t}_Total,1,${t}_Total);`);
    else if (n === 6) out.push(`[XIC(${t}_A)XIO(${t}_B),XIC(${t}_C)[XIC(${t}_D),XIO(${t}_E)]]OTE(${t}_Valve);`);
    else out.push(`XIC(${t}_Valve)XIC(${t}_Pump)OTL(${t}_Alarm);`);
  }
  return out.join("\n");
}

describe("(e) performance", () => {
  it("analyses a 2000-rung program in < 1.5 s and simulates it fast", () => {
    const text = bigProgram(2000);
    analyzeProgram(bigProgram(50)); // warm up the JIT
    const t0 = performance.now();
    const a = analyzeProgram(text, { now: () => performance.now() });
    const ms = performance.now() - t0;
    expect(a.parse.rungs).toHaveLength(2000);
    expect(a.parse.errors).toEqual([]);
    console.info(`2000 rungs: ${ms.toFixed(0)} ms total`, Object.fromEntries(Object.entries(a.timingsMs).map(([k, v]) => [k, Math.round(v)])));
    expect(ms).toBeLessThan(1500);

    const sim = createSimulator(a.parse.rungs);
    const s0 = performance.now();
    for (let k = 0; k < 100; k++) sim.scan(10);
    const perScan = (performance.now() - s0) / 100;
    console.info(`simulator: ${perScan.toFixed(2)} ms per scan of 2000 rungs`);
    expect(perScan).toBeLessThan(20);
  });
});
