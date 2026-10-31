import { useMemo, useState } from "react";
import { BookOpen, Crosshair, Lightbulb } from "lucide-react";
import type { Finding, Severity } from "../../engine";
import { SEVERITY_ORDER, SeverityBadge } from "./bits";

interface Props {
  findings: Finding[];
  onLocate?: (instrId: string) => void;
}

export function FaultList({ findings, onLocate }: Props) {
  const [filter, setFilter] = useState<Severity | "all">("all");
  const [basis, setBasis] = useState<"all" | "rule" | "heuristic">("all");
  const shown = useMemo(
    () => findings.filter((f) => (filter === "all" || f.severity === filter) && (basis === "all" || f.basis === basis)),
    [findings, filter, basis],
  );

  if (!findings.length) {
    return <p className="py-10 text-center text-emerald-300" style={{ fontSize: "0.85rem" }}>No findings. Every rule passed for this program.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap" role="group" aria-label="Filter findings">
        {(["all", ...SEVERITY_ORDER] as const).map((s) => {
          const n = s === "all" ? findings.length : findings.filter((f) => f.severity === s).length;
          return (
            <button
              key={s}
              type="button"
              aria-pressed={filter === s}
              onClick={() => setFilter(s)}
              disabled={n === 0 && s !== "all"}
              className={`px-2.5 py-1 rounded-lg border capitalize disabled:opacity-40 ${filter === s ? "bg-slate-700 border-slate-500 text-slate-100" : "bg-slate-800/50 border-slate-700 text-slate-400 hover:text-slate-200"}`}
              style={{ fontSize: "0.72rem" }}
            >
              {s} ({n})
            </button>
          );
        })}
        <select
          aria-label="Filter by basis"
          value={basis}
          onChange={(e) => setBasis(e.target.value as typeof basis)}
          className="ml-auto px-2 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-300"
          style={{ fontSize: "0.72rem" }}
        >
          <option value="all">Rules + heuristics</option>
          <option value="rule">Deterministic rules only</option>
          <option value="heuristic">Heuristics only</option>
        </select>
      </div>

      <ul className="space-y-2.5">
        {shown.map((f) => (
          <li key={f.id} className="p-3.5 rounded-xl bg-slate-950 border border-slate-700/80">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <SeverityBadge severity={f.severity} />
                <h3 className="text-slate-100" style={{ fontSize: "0.86rem", fontWeight: 600 }}>{f.title}</h3>
              </div>
              {onLocate && f.instrIds.length > 0 && (
                <button
                  type="button"
                  onClick={() => onLocate(f.instrIds[0])}
                  className="flex items-center gap-1 px-2 py-1 rounded-md text-cyan-300 hover:bg-slate-800 flex-shrink-0"
                  style={{ fontSize: "0.7rem" }}
                  aria-label={`Show "${f.title}" in the ladder diagram`}
                >
                  <Crosshair size={12} aria-hidden /> Show
                </button>
              )}
            </div>
            <p className="mt-1 text-slate-500" style={{ fontSize: "0.68rem" }}>
              <span className="font-mono">{f.rule}</span>
              {" · "}
              {f.basis === "rule" ? "deterministic rule" : "heuristic"} · confidence {f.confidence}%
              {f.rungs.length ? ` · rung${f.rungs.length > 1 ? "s" : ""} ${f.rungs.join(", ")}` : ""}
            </p>
            {f.tags.length > 0 && (
              <p className="mt-1.5 flex flex-wrap gap-1">
                {f.tags.slice(0, 12).map((t) => (
                  <code key={t} className="px-1.5 py-0.5 rounded bg-slate-800 text-cyan-200" style={{ fontSize: "0.68rem" }}>{t}</code>
                ))}
              </p>
            )}
            <p className="mt-2 text-slate-300 whitespace-pre-wrap" style={{ fontSize: "0.78rem", lineHeight: 1.5 }}>{f.description}</p>
            <p className="mt-2 flex items-start gap-1.5 text-emerald-200/90 whitespace-pre-wrap" style={{ fontSize: "0.76rem", lineHeight: 1.5 }}>
              <Lightbulb size={13} className="mt-0.5 flex-shrink-0" aria-hidden /> {f.recommendation}
            </p>
            {f.standard && (
              <p className="mt-1.5 flex items-center gap-1.5 text-slate-500" style={{ fontSize: "0.68rem" }}>
                <BookOpen size={11} aria-hidden /> {f.standard}
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
