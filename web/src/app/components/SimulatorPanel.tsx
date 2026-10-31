// Scan-cycle simulator on the parsed program (engine/simulate.ts, Logix rung-condition semantics).
// Inputs are modelled as field devices: a device is actuated or released, and its wiring
// (NO / NC) decides the bit the PLC sees. Stop and E-stop style devices default to NC wiring
// (fail-safe practice), so "released" reads 1 for them.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pause, Play, RotateCcw, StepForward, TriangleAlert } from "lucide-react";
import { buildXref, createSimulator, tagKey, type Rung, type ScanResult } from "../../engine";
import { LadderDiagram } from "./LadderDiagram";

const FAILSAFE_NAME = /(^|[^A-Z])(E?_?STOP|ESTOP|EMERG|EMG|OL|OVERLOAD|O_L|TRIP|GUARD)([^A-Z]|$)/i;
const SCAN_OPTIONS = [10, 50, 100, 250, 1000];

type Wiring = "NO" | "NC";

export function defaultWiring(tag: string): Wiring {
  return FAILSAFE_NAME.test(tag.replace(/[^A-Za-z0-9]+/g, "_")) ? "NC" : "NO";
}

export function SimulatorPanel({ rungs }: { rungs: Rung[] }) {
  const sim = useMemo(() => createSimulator(rungs), [rungs]);
  const xref = useMemo(() => buildXref(rungs), [rungs]);
  const [, setTick] = useState(0);
  const [running, setRunning] = useState(false);
  const [scanMs, setScanMs] = useState(100);
  const [last, setLast] = useState<ScanResult | null>(null);
  const [fault, setFault] = useState<string | null>(null);
  const [wiring, setWiring] = useState<Record<string, Wiring>>({});
  const [actuated, setActuated] = useState<Record<string, boolean>>({});
  const [numbers, setNumbers] = useState<Record<string, number>>({});

  const boolInputs = sim.inputs.filter((t) => (sim.types.get(tagKey(t)) ?? "BOOL") === "BOOL");
  const numInputs = sim.inputs.filter((t) => (sim.types.get(tagKey(t)) ?? "BOOL") !== "BOOL");
  const inputKeys = new Set(sim.inputs.map(tagKey));
  const computed = sim.tags.filter((t) => !inputKeys.has(tagKey(t)));
  const instances = [...xref.instances.values()];

  const wiringOf = useCallback((t: string): Wiring => wiring[t] ?? defaultWiring(t), [wiring]);
  const bitOf = useCallback((t: string) => (wiringOf(t) === "NO" ? !!actuated[t] : !actuated[t]), [actuated, wiringOf]);

  // keep the latest input picture in a ref so the interval never runs on stale state
  const inputsRef = useRef<() => void>(() => undefined);
  inputsRef.current = () => {
    for (const t of boolInputs) sim.setInput(t, bitOf(t));
    for (const t of numInputs) sim.setInput(t, numbers[t] ?? 0);
  };

  const doScan = useCallback(() => {
    inputsRef.current();
    const res = sim.scan(scanMs);
    setLast(res);
    if (res.fault) {
      setFault(res.fault);
      setRunning(false);
    }
    setTick((n) => n + 1);
  }, [sim, scanMs]);

  useEffect(() => {
    setRunning(false);
    setLast(null);
    setFault(null);
  }, [sim]);

  useEffect(() => {
    if (!running) return;
    const id = setInterval(doScan, scanMs);
    return () => clearInterval(id);
  }, [running, doScan, scanMs]);

  const reset = () => {
    setRunning(false);
    sim.reset();
    setLast(null);
    setFault(null);
    setTick((n) => n + 1);
  };

  const value = (t: string) => {
    const v = sim.read(t);
    return typeof v === "boolean" ? v : Number.isInteger(v) ? v : Number(v.toFixed(3));
  };

  if (!rungs.length) return <p className="py-10 text-center text-slate-500" style={{ fontSize: "0.85rem" }}>Analyse a program to simulate it.</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => setRunning((r) => !r)}
          disabled={!!fault}
          className={`flex items-center gap-1.5 px-3 py-2 rounded-lg ${running ? "bg-amber-500 text-slate-950" : "bg-emerald-500 text-slate-950"} disabled:opacity-40`}
          style={{ fontSize: "0.8rem", fontWeight: 600 }}
        >
          {running ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />} {running ? "Pause" : "Run"}
        </button>
        <button type="button" onClick={doScan} disabled={running || !!fault} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 disabled:opacity-40" style={{ fontSize: "0.8rem" }}>
          <StepForward size={14} aria-hidden /> One scan
        </button>
        <button type="button" onClick={reset} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200" style={{ fontSize: "0.8rem" }}>
          <RotateCcw size={14} aria-hidden /> Reset
        </button>
        <label className="flex items-center gap-1.5 text-slate-400" style={{ fontSize: "0.75rem" }}>
          Scan time
          <select value={scanMs} onChange={(e) => setScanMs(Number(e.target.value))} className="px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200">
            {SCAN_OPTIONS.map((ms) => <option key={ms} value={ms}>{ms} ms</option>)}
          </select>
        </label>
        <span className="ml-auto text-slate-500 font-mono" style={{ fontSize: "0.72rem" }} aria-live="polite">
          scan {sim.scanCount}
          {running ? " · running" : ""}
        </span>
      </div>

      {fault && (
        <p role="alert" className="flex items-center gap-2 p-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300" style={{ fontSize: "0.78rem" }}>
          <TriangleAlert size={14} aria-hidden /> Scan aborted: {fault}. Reset to continue.
        </p>
      )}
      {last && last.warnings.length > 0 && (
        <ul className="text-amber-200/80" style={{ fontSize: "0.72rem" }}>
          {[...new Set(last.warnings)].slice(0, 5).map((w, i) => <li key={i}>• {w}</li>)}
        </ul>
      )}

      <div className="grid lg:grid-cols-2 gap-3">
        <section className="lg:col-span-2 p-3 rounded-xl bg-slate-950 border border-slate-700/70" aria-label="Field inputs">
          <h3 className="text-slate-300 mb-2" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Field inputs</h3>
          {boolInputs.length === 0 && numInputs.length === 0 && <p className="text-slate-500" style={{ fontSize: "0.72rem" }}>This program reads no external inputs.</p>}
          <ul className="grid sm:grid-cols-2 xl:grid-cols-3 gap-1.5">
            {boolInputs.map((t) => {
              const bit = bitOf(t);
              const on = !!actuated[t];
              return (
                <li key={t} className="flex items-center gap-2" style={{ fontSize: "0.74rem" }}>
                  <button
                    type="button"
                    aria-pressed={on}
                    onClick={() => setActuated((a) => ({ ...a, [t]: !a[t] }))}
                    className={`flex-1 min-w-0 text-left px-2 py-1.5 rounded-lg border truncate ${on ? "bg-cyan-500/15 border-cyan-500/40 text-cyan-200" : "bg-slate-800/60 border-slate-700 text-slate-300"}`}
                    style={{ fontSize: "0.74rem" }}
                    title={`${t}: ${on ? "actuated" : "released"}, bit = ${bit ? 1 : 0}`}
                  >
                    <span className="font-mono">{t}</span>
                    <span className="text-slate-500"> · {on ? "actuated" : "released"}</span>
                  </button>
                  <select
                    aria-label={`${t} wiring`}
                    value={wiringOf(t)}
                    onChange={(e) => setWiring((w) => ({ ...w, [t]: e.target.value as Wiring }))}
                    className="px-1 py-1 rounded bg-slate-800 border border-slate-700 text-slate-300"
                    style={{ fontSize: "0.68rem" }}
                  >
                    <option value="NO">NO</option>
                    <option value="NC">NC</option>
                  </select>
                  <span className={`w-6 text-center font-mono ${bit ? "text-emerald-300" : "text-slate-500"}`} aria-label={`bit ${bit ? 1 : 0}`}>{bit ? 1 : 0}</span>
                </li>
              );
            })}
            {numInputs.map((t) => (
              <li key={t} className="flex items-center gap-2" style={{ fontSize: "0.74rem" }}>
                <label className="flex-1 font-mono text-slate-300 truncate" htmlFor={`num-${t}`}>{t}</label>
                <input
                  id={`num-${t}`}
                  type="number"
                  value={numbers[t] ?? 0}
                  onChange={(e) => setNumbers((n) => ({ ...n, [t]: Number(e.target.value) || 0 }))}
                  className="w-24 px-2 py-1 rounded bg-slate-800 border border-slate-700 text-slate-200"
                />
              </li>
            ))}
          </ul>
          <p className="mt-2 text-slate-600" style={{ fontSize: "0.66rem" }}>NC-wired devices read 1 when released. Stop, E-stop and overload devices default to NC.</p>
        </section>

        <section className="p-3 rounded-xl bg-slate-950 border border-slate-700/70" aria-label="Outputs and internal tags">
          <h3 className="text-slate-300 mb-2" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Outputs and internal tags</h3>
          <ul className="space-y-1">
            {computed.map((t) => {
              const v = value(t);
              const changed = last?.changed.includes(t);
              return (
                <li key={t} className="flex items-center justify-between gap-2" style={{ fontSize: "0.74rem" }}>
                  <span className="font-mono text-slate-300 truncate">{t}</span>
                  {typeof v === "boolean" ? (
                    <span className={`px-2 py-0.5 rounded-full border ${v ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" : "bg-slate-800 border-slate-700 text-slate-500"} ${changed ? "ring-1 ring-cyan-400" : ""}`}>
                      {v ? "ON" : "off"}
                    </span>
                  ) : (
                    <span className={`font-mono text-slate-200 ${changed ? "text-cyan-300" : ""}`}>{v}</span>
                  )}
                </li>
              );
            })}
          </ul>
        </section>

        <section className="p-3 rounded-xl bg-slate-950 border border-slate-700/70" aria-label="Timers and counters">
          <h3 className="text-slate-300 mb-2" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Timers and counters</h3>
          {instances.length === 0 && <p className="text-slate-500" style={{ fontSize: "0.72rem" }}>None in this program.</p>}
          <ul className="space-y-2">
            {instances.map((inst) => {
              const t = inst.kind === "timer" ? sim.timer(inst.display) : undefined;
              const c = inst.kind === "counter" ? sim.counter(inst.display) : undefined;
              const pre = t?.PRE ?? c?.PRE ?? 0;
              const acc = t?.ACC ?? c?.ACC ?? 0;
              const pct = pre > 0 ? Math.min(100, (acc / pre) * 100) : 0;
              const dn = t?.DN ?? c?.DN ?? false;
              return (
                <li key={inst.key} style={{ fontSize: "0.72rem" }}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-slate-300 truncate">{inst.display} <span className="text-slate-600">{inst.mnemonics.join("/")}</span></span>
                    <span className={dn ? "text-emerald-300" : "text-slate-500"}>{dn ? "DN" : t?.TT ? "TT" : t?.EN ? "EN" : "—"}</span>
                  </div>
                  <div className="h-1.5 mt-1 rounded-full bg-slate-800 overflow-hidden" role="progressbar" aria-valuemin={0} aria-valuemax={pre} aria-valuenow={acc} aria-label={`${inst.display} accumulated`}>
                    <div className="h-full bg-cyan-500" style={{ width: `${pct}%` }} />
                  </div>
                  <p className="text-slate-500 font-mono" style={{ fontSize: "0.66rem" }}>
                    ACC {Math.round(acc)} / PRE {Math.round(pre)}{inst.kind === "timer" ? " ms" : ""}
                  </p>
                </li>
              );
            })}
          </ul>
        </section>
      </div>

      <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
        <p className="text-slate-500 mb-2" style={{ fontSize: "0.7rem" }}>Green = power flowing in the last scan.</p>
        <LadderDiagram rungs={rungs} power={last?.power} idPrefix="sim" />
      </div>
    </div>
  );
}
