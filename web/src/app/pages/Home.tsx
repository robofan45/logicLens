import { Link } from "react-router";
import { ArrowRight, Binary, Bot, Camera, Check, Code2, Lock, Play, ShieldCheck, Wrench } from "lucide-react";
import { RULE_COUNT } from "../lib/rules";

const FEATURES = [
  { icon: <Camera size={18} aria-hidden />, title: "Screenshot or text in", text: "Upload an HMI or IDE screenshot (recognised by the LogicLens server), or paste rungs copied from Studio 5000 / RSLogix as neutral text." },
  { icon: <ShieldCheck size={18} aria-hidden />, title: `${RULE_COUNT} checks, rules first`, text: "Double coils, latches without unlatch, dead and always-true rungs, timer and counter mistakes, jumps, MCR zones, fail-safe stop wiring, E-stop handling and more." },
  { icon: <Binary size={18} aria-hidden />, title: "Signal trace", text: "What drives every output, written as a boolean condition, plus a full cross-reference and scan-order notes." },
  { icon: <Wrench size={18} aria-hidden />, title: "Corrections you can review", text: "Before/after rungs for structural fixes, marked safe or needs-confirmation, with verification steps." },
  { icon: <Code2 size={18} aria-hidden />, title: "IEC 61131-3 Structured Text", text: "Exported with the ladder's scan semantics; the test suite checks it against the simulator on hundreds of random programs." },
  { icon: <Play size={18} aria-hidden />, title: "Scan-cycle simulator", text: "Actuate field devices (with NO/NC wiring), watch timers and counters, and see power flow rung by rung." },
  { icon: <Bot size={18} aria-hidden />, title: "Optional AI explanations", text: "Plain-language summaries and follow-up questions through Claude, clearly separated from the rule-based results." },
  { icon: <Lock size={18} aria-hidden />, title: "Private by design", text: "Text analysis runs in your browser. Images are processed in server memory and never stored. History stays in your browser." },
];

const PLANS = [
  { name: "Free", price: "$0", items: ["Text analysis, all checks", "Structured Text export", "Simulator", "10 image recognitions / month"] },
  { name: "Pro", price: "$29/mo", items: ["200 image recognitions / month", "AI explanations and chat", "Report export", "Email support"] },
  { name: "Team", price: "$79/mo", items: ["Unlimited recognitions", "10 seats, shared library", "Offline / on-prem option", "Priority support"] },
  { name: "Enterprise", price: "Talk to us", items: ["Air-gapped deployment", "Custom rules and models", "SSO, audit logging", "Dedicated support"] },
];

export function Home() {
  return (
    <div className="min-h-full">
      <section className="relative overflow-hidden border-b border-slate-800">
        <div className="absolute inset-0 pointer-events-none" aria-hidden style={{ background: "radial-gradient(60rem 30rem at 20% -10%, rgba(34,211,238,0.10), transparent 60%)" }} />
        <div className="relative max-w-6xl mx-auto px-4 py-16 lg:py-24">
          <p className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-cyan-500/30 bg-cyan-500/5 text-cyan-300" style={{ fontSize: "0.72rem" }}>
            For automation and controls engineers
          </p>
          <h1 className="mt-5 text-slate-50 max-w-3xl" style={{ fontSize: "clamp(2rem, 4.5vw, 3.2rem)", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.08 }}>
            Find the fault in a PLC rung <span className="text-cyan-400">before</span> it finds you.
          </h1>
          <p className="mt-5 text-slate-400 max-w-2xl" style={{ fontSize: "1.02rem", lineHeight: 1.65 }}>
            LogicLens reads ladder logic from a screenshot or from text, checks it against {RULE_COUNT} rules and heuristics, traces every output, proposes corrections,
            exports IEC 61131-3 Structured Text and simulates the scan. Rockwell, Siemens, Schneider and generic IEC notation.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/analyzer?sample=faulty-demo" className="inline-flex items-center gap-2 px-5 py-3 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950" style={{ fontWeight: 700 }}>
              Try it on a faulty program <ArrowRight size={17} aria-hidden />
            </Link>
            <Link to="/analyzer" className="inline-flex items-center gap-2 px-5 py-3 rounded-xl bg-slate-800 border border-slate-700 hover:bg-slate-700 text-slate-200" style={{ fontWeight: 500 }}>
              Analyse your own
            </Link>
          </div>
          <pre className="mt-10 max-w-2xl p-4 rounded-xl bg-slate-900/80 border border-slate-800 text-slate-300 overflow-x-auto" style={{ fontSize: "0.78rem", fontFamily: "'Fira Code', monospace" }}>
{`// paste rungs straight from Studio 5000 / RSLogix
[XIC(Start_PB),XIC(Motor_Run)]XIO(Stop_PB)OTE(Motor_Run);
XIC(Remote_Start)OTE(Motor_Run);   ← double coil: rung 0 is overwritten`}
          </pre>
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-4 py-14" aria-labelledby="features">
        <h2 id="features" className="text-slate-100" style={{ fontSize: "1.4rem", fontWeight: 700 }}>What it does today</h2>
        <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {FEATURES.map((f) => (
            <div key={f.title} className="p-4 rounded-xl bg-slate-900 border border-slate-800">
              <div className="w-9 h-9 rounded-lg bg-cyan-500/10 text-cyan-300 flex items-center justify-center">{f.icon}</div>
              <h3 className="mt-3 text-slate-100" style={{ fontSize: "0.92rem", fontWeight: 600 }}>{f.title}</h3>
              <p className="mt-1.5 text-slate-400" style={{ fontSize: "0.8rem", lineHeight: 1.55 }}>{f.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="max-w-6xl mx-auto px-4 pb-14" aria-labelledby="honesty">
        <div className="p-5 rounded-xl border border-amber-500/20 bg-amber-500/5">
          <h2 id="honesty" className="text-amber-200" style={{ fontSize: "1rem", fontWeight: 600 }}>What it is not</h2>
          <p className="mt-2 text-amber-100/70" style={{ fontSize: "0.85rem", lineHeight: 1.6 }}>
            LogicLens is an advisory tool. It does not certify safety functions, and it cannot see field wiring, hardware configuration or code outside the rungs you give it.
            Image recognition is a pilot trained on synthetic diagrams: always review the recognised rungs against the picture. Emergency stops belong in hard-wired or
            safety-rated circuits, never only in standard PLC logic.
          </p>
        </div>
      </section>

      <section className="border-t border-slate-800 bg-slate-900/40" aria-labelledby="plans">
        <div className="max-w-6xl mx-auto px-4 py-14">
          <h2 id="plans" className="text-slate-100" style={{ fontSize: "1.4rem", fontWeight: 700 }}>Plans <span className="text-slate-500" style={{ fontSize: "0.85rem", fontWeight: 400 }}>(planned pricing, billing not live yet)</span></h2>
          <div className="mt-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {PLANS.map((p, i) => (
              <div key={p.name} className={`p-5 rounded-xl border ${i === 1 ? "border-cyan-500/40 bg-cyan-500/5" : "border-slate-800 bg-slate-900"}`}>
                <h3 className="text-slate-100" style={{ fontWeight: 600 }}>{p.name}</h3>
                <p className="mt-1 text-slate-50" style={{ fontSize: "1.5rem", fontWeight: 800 }}>{p.price}</p>
                <ul className="mt-3 space-y-1.5">
                  {p.items.map((it) => (
                    <li key={it} className="flex items-start gap-2 text-slate-400" style={{ fontSize: "0.8rem" }}>
                      <Check size={14} className="text-cyan-400 mt-0.5 flex-shrink-0" aria-hidden /> {it}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t border-slate-800">
        <div className="max-w-6xl mx-auto px-4 py-6 text-slate-600 flex flex-wrap gap-x-6 gap-y-2" style={{ fontSize: "0.75rem" }}>
          <span>LogicLens v2</span>
          <Link to="/docs" className="hover:text-slate-400">Docs</Link>
          <Link to="/history" className="hover:text-slate-400">History</Link>
          <span>Advisory only. Verify before you change a live system.</span>
        </div>
      </footer>
    </div>
  );
}
