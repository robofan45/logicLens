import { CheckCircle2, CircleDashed, ShieldAlert, XCircle } from "lucide-react";
import type { Analysis, ChecklistKey } from "../../engine";
import { SEVERITY_ORDER, SEVERITY_STYLE } from "./bits";

const GRADE_STYLE: Record<string, string> = {
  Healthy: "text-emerald-300",
  "Minor issues": "text-sky-300",
  "Needs attention": "text-amber-300",
  Critical: "text-red-300",
};

const CHECK_LABEL: Record<ChecklistKey, string> = {
  RACE_CONDITION: "Race condition",
  MISSING_INTERLOCK: "Missing interlock",
  MISSING_SAFETY_INPUT: "Missing safety input",
  COIL_CONFLICT: "Coil conflict",
  LATCH_WITHOUT_UNLATCH: "Latch without unlatch",
  BYPASSED_SAFETY: "Bypassed safety",
  DEAD_RUNG: "Dead rung",
  ALWAYS_TRUE: "Always-true logic",
  MISSING_SEAL_IN: "Missing seal-in",
  TIMER_OVERFLOW: "Timer preset / overflow",
  COUNTER_NO_RESET: "Counter without reset",
  WRONG_CONTACT_TYPE: "Wrong contact type",
  BROKEN_BRANCH: "Broken branch",
  MISSING_PERMISSIVE: "Missing permissive",
  REDUNDANT_LOGIC: "Redundant logic",
  SUBOPTIMAL_ORDER: "Scan-order delay",
  NAMING_INCONSISTENCY: "Naming consistency",
  MISSING_COMMENT: "Rung comments",
  UNUSED_TAG: "Unused tags",
};

export function OverviewPanel({ analysis }: { analysis: Analysis }) {
  const { faults, stats } = analysis;
  const stat = (label: string, value: number) => (
    <div className="p-2.5 rounded-lg bg-slate-800/60 border border-slate-700/70 text-center">
      <p className="text-slate-100" style={{ fontSize: "1.1rem", fontWeight: 700 }}>{value}</p>
      <p className="text-slate-500" style={{ fontSize: "0.68rem" }}>{label}</p>
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-3 gap-3">
        <div className="sm:col-span-1 p-4 rounded-xl bg-slate-950 border border-slate-700 text-center">
          <p className="text-slate-500" style={{ fontSize: "0.7rem", textTransform: "uppercase", letterSpacing: "0.06em" }}>Risk score</p>
          <p className={GRADE_STYLE[faults.grade] ?? "text-slate-100"} style={{ fontSize: "2.2rem", fontWeight: 800, lineHeight: 1.1 }}>
            {faults.riskScore}
            <span className="text-slate-600" style={{ fontSize: "1rem", fontWeight: 500 }}>/100</span>
          </p>
          <p className={GRADE_STYLE[faults.grade]} style={{ fontSize: "0.8rem", fontWeight: 600 }}>{faults.grade}</p>
          <div className="mt-3 flex justify-center gap-1.5 flex-wrap">
            {SEVERITY_ORDER.map((s) => (
              <span key={s} className={`px-1.5 py-0.5 rounded border ${SEVERITY_STYLE[s]}`} style={{ fontSize: "0.68rem" }}>
                {faults.counts[s]} {s}
              </span>
            ))}
          </div>
        </div>
        <div className="sm:col-span-2 grid grid-cols-3 sm:grid-cols-4 gap-2 content-start">
          {stat("Rungs", stats.rungs)}
          {stat("Instructions", stats.instructions)}
          {stat("Tags", stats.tags)}
          {stat("Inputs", stats.inputs)}
          {stat("Outputs", stats.outputs)}
          {stat("Timers", stats.timers)}
          {stat("Counters", stats.counters)}
          {stat("Parse errors", stats.parseErrors)}
        </div>
      </div>

      <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20 text-amber-200/80" style={{ fontSize: "0.75rem" }}>
        <ShieldAlert size={15} className="mt-0.5 flex-shrink-0" aria-hidden />
        <p>
          Advisory only. Rule-based findings are exact for the logic shown; heuristic ones depend on tag names and say so. A qualified engineer must
          verify any change before it reaches a live system. This is not a functional-safety verification (IEC 61508 / IEC 61511).
        </p>
      </div>

      <div>
        <h3 className="text-slate-300 mb-2" style={{ fontSize: "0.82rem", fontWeight: 600 }}>Checklist (19 items)</h3>
        <ul className="grid sm:grid-cols-2 gap-1.5">
          {(Object.keys(faults.checklist) as ChecklistKey[]).map((k) => {
            const e = faults.checklist[k];
            const icon =
              e.status === "FOUND" ? <XCircle size={14} className="text-red-400" aria-hidden /> :
              e.status === "NOT_FOUND" ? <CheckCircle2 size={14} className="text-emerald-400" aria-hidden /> :
              <CircleDashed size={14} className="text-slate-500" aria-hidden />;
            const word = e.status === "FOUND" ? "found" : e.status === "NOT_FOUND" ? "not found" : "not applicable";
            return (
              <li key={k} className="flex items-start gap-2 px-2.5 py-1.5 rounded-lg bg-slate-800/40 border border-slate-700/60" title={e.reason ?? undefined}>
                <span className="mt-0.5">{icon}</span>
                <span className="flex-1 min-w-0">
                  <span className="text-slate-200" style={{ fontSize: "0.76rem" }}>{CHECK_LABEL[k]}</span>
                  <span className="text-slate-500" style={{ fontSize: "0.68rem" }}> · {word}</span>
                  {e.reason && e.status !== "FOUND" && <span className="block text-slate-600 truncate" style={{ fontSize: "0.66rem" }}>{e.reason}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
