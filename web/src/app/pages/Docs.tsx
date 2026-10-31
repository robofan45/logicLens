import { Link } from "react-router";
import { ALIASES, LIMITS, SPEC } from "../../engine";
import { RULE_DOCS } from "../lib/rules";

const SECTIONS = [
  { id: "start", label: "Quick start" },
  { id: "syntax", label: "Ladder text" },
  { id: "checks", label: "Checks" },
  { id: "simulator", label: "Simulator" },
  { id: "st", label: "Structured Text" },
  { id: "server", label: "Server and privacy" },
];

const code = "px-1.5 py-0.5 rounded bg-slate-800 text-cyan-200";

export function Docs() {
  const aliasesFor = (m: string) => Object.entries(ALIASES).filter(([, v]) => v === m).map(([k]) => k);
  return (
    <div className="max-w-5xl mx-auto px-4 py-6 lg:flex gap-8">
      <nav aria-label="Docs sections" className="lg:w-44 flex-shrink-0 mb-6 lg:mb-0">
        <ul className="lg:sticky lg:top-6 flex lg:flex-col gap-1 flex-wrap">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="block px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800" style={{ fontSize: "0.82rem" }}>{s.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      <article className="flex-1 min-w-0 space-y-10 text-slate-300" style={{ fontSize: "0.86rem", lineHeight: 1.65 }}>
        <section id="start" className="scroll-mt-6">
          <h1 className="text-slate-100" style={{ fontSize: "1.35rem", fontWeight: 700 }}>LogicLens documentation</h1>
          <ol className="mt-3 list-decimal ml-5 space-y-1.5">
            <li>Open the <Link to="/analyzer" className="text-cyan-300 hover:underline">Analyzer</Link>.</li>
            <li>Paste rungs as text (copy a rung in Studio 5000 or RSLogix and paste: the clipboard holds neutral text), or switch to <em>Image</em> and upload a screenshot.</li>
            <li>Pick the PLC platform (it tunes address-style rules) and press <strong>Analyse</strong> (or <kbd className={code}>Ctrl</kbd>+<kbd className={code}>Enter</kbd>).</li>
            <li>Read the risk score and findings, check the ladder view, load suggested corrections, export Structured Text or a report, and try the logic in the simulator.</li>
          </ol>
        </section>

        <section id="syntax" className="scroll-mt-6">
          <h2 className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>Ladder text</h2>
          <p className="mt-2">
            One rung per line (or several separated by <code className={code}>;</code>). Instructions are written <code className={code}>MNEMONIC(operand,…)</code>; series
            elements follow each other, a branch is <code className={code}>[leg,leg]</code> and an empty leg is a wire. Lines starting with <code className={code}>//</code> or{" "}
            <code className={code}>#</code> are comments for the next rung. A label such as <code className={code}>0003:</code> or <code className={code}>Rung 3:</code> sets the rung number.
            Operands may be tags (<code className={code}>I:1/0</code>, <code className={code}>%I0.0</code>, <code className={code}>Local:1:I.Data.0</code>, <code className={code}>"Motor Start"</code>),
            numbers (<code className={code}>16#FF</code>), IEC times (<code className={code}>T#5s</code>) or <code className={code}>?</code> for an unread operand.
          </p>
          <pre className="mt-3 p-3 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto text-slate-200" style={{ fontSize: "0.76rem", fontFamily: "'Fira Code', monospace" }}>
{`// Motor M-101 start/stop (Stop_PB wired NC)
XIC(Stop_PB)[XIC(Start_PB),XIC(Motor_Run)]OTE(Motor_Run);
XIC(Motor_Run)TON(Run_Timer,5000,0);          // Logix timer: preset ms, accum
XIC(I:1/0)TON(T4:0,0.01,500,0);               // SLC timer: base s, preset, accum
NO(Start)TON(T1,T#5s);                        // IEC aliases`}
          </pre>
          <div className="mt-4 overflow-x-auto rounded-xl border border-slate-700">
            <table className="w-full" style={{ fontSize: "0.76rem" }}>
              <caption className="sr-only">Supported instructions</caption>
              <thead>
                <tr className="bg-slate-800/60 text-slate-400 text-left">
                  <th scope="col" className="px-3 py-2 font-medium">Instruction</th>
                  <th scope="col" className="px-3 py-2 font-medium">Aliases</th>
                  <th scope="col" className="px-3 py-2 font-medium">Operands</th>
                  <th scope="col" className="px-3 py-2 font-medium">Role</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(SPEC).map(([m, [lo, hi, role]]) => (
                  <tr key={m} className="border-t border-slate-800">
                    <td className="px-3 py-1.5 font-mono text-slate-100">{m}</td>
                    <td className="px-3 py-1.5 font-mono text-slate-400">{aliasesFor(m).join(", ") || "—"}</td>
                    <td className="px-3 py-1.5 text-slate-400">{lo === hi ? lo : `${lo}–${hi}`}</td>
                    <td className="px-3 py-1.5 text-slate-400">{role === "in" ? "condition" : "output"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-slate-500" style={{ fontSize: "0.78rem" }}>
            Limits: {LIMITS.program_chars.toLocaleString()} characters, {LIMITS.rungs.toLocaleString()} rungs, {LIMITS.instructions} instructions per rung, branch depth{" "}
            {LIMITS.depth}, {LIMITS.operand_chars} characters per operand. The full grammar is in <code className={code}>contract/README.md</code>.
          </p>
        </section>

        <section id="checks" className="scroll-mt-6">
          <h2 className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>Checks ({Object.keys(RULE_DOCS).length})</h2>
          <p className="mt-2">
            <strong>Rules</strong> are exact for the logic given. <strong>Heuristics</strong> read intent from tag names (START, STOP, MOTOR, ESTOP…) and carry a lower
            confidence; treat them as questions to answer, not verdicts. Every finding maps onto the 19-item checklist of the LogicLens prompt playbook. The risk score
            combines findings as 100 × (1 − Π(1 − w)) with w = 0.45 critical, 0.25 high, 0.10 medium, 0.02 low.
          </p>
          <ul className="mt-3 grid md:grid-cols-2 gap-2">
            {Object.entries(RULE_DOCS).map(([id, r]) => (
              <li key={id} className="p-3 rounded-xl bg-slate-900 border border-slate-800">
                <p className="text-slate-100" style={{ fontWeight: 600, fontSize: "0.82rem" }}>
                  {r.title} <span className={`ml-1 px-1.5 rounded ${r.basis === "rule" ? "bg-emerald-500/10 text-emerald-300" : "bg-amber-500/10 text-amber-300"}`} style={{ fontSize: "0.62rem" }}>{r.basis}</span>
                </p>
                <p className="font-mono text-slate-600" style={{ fontSize: "0.66rem" }}>{id}</p>
                <p className="mt-1 text-slate-400" style={{ fontSize: "0.78rem" }}>{r.what}</p>
              </li>
            ))}
          </ul>
        </section>

        <section id="simulator" className="scroll-mt-6">
          <h2 className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>Simulator</h2>
          <p className="mt-2">
            Rungs run top to bottom; within a rung power flows left to right (series = AND, branch = OR) and output instructions pass power on, as in a Logix
            controller. Writes are visible to later rungs in the same scan. Timers accumulate the scan time you choose. Tags the program never writes are
            inputs. Each input is a field device you actuate or release, and its wiring decides the bit: an <strong>NC</strong>-wired device reads 1 when
            released. Stop, E-stop and overload devices default to NC because that is the fail-safe practice.
          </p>
        </section>

        <section id="st" className="scroll-mt-6">
          <h2 className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>Structured Text export</h2>
          <p className="mt-2">
            Generates an IEC 61131-3 <code className={code}>PROGRAM</code> with declarations and one call per timer/counter instance per scan. Tag names become
            valid identifiers (the original name stays in a comment). Forward jumps become <code className={code}>IF NOT … THEN</code> blocks and MCR zones
            become IF/ELSE blocks. Untranslatable constructs (backward jumps, JSR targets) are commented and listed as warnings. RTO becomes the vendor block{" "}
            <code className={code}>TONR</code>. Review the code before importing it into your IDE.
          </p>
        </section>

        <section id="server" className="scroll-mt-6">
          <h2 className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>Server and privacy</h2>
          <ul className="mt-2 list-disc ml-5 space-y-1.5">
            <li>Parsing, checks, trace, corrections, Structured Text and the simulator run entirely in your browser. They work offline.</li>
            <li>Image recognition and AI explanations need the LogicLens server (<code className={code}>backend/</code>). Images are decoded in memory and never written to disk or logs.</li>
            <li>AI explanations send the program text and findings to the server, which calls Anthropic's Claude API. Nothing is sent unless you press the AI buttons.</li>
            <li>History is kept in this browser's local storage (newest 50 analyses, no images). Delete it any time from the History page.</li>
            <li>Endpoints: <code className={code}>POST /api/analyze/parse</code> (image), <code className={code}>POST /api/analyze/text</code>, <code className={code}>POST /api/analyze/explain</code>,{" "}
              <code className={code}>POST /api/chat</code>, <code className={code}>GET /api/meta</code>, <code className={code}>GET /health</code>. See <code className={code}>backend/README.md</code>.</li>
          </ul>
        </section>
      </article>
    </div>
  );
}
