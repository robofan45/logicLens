import { useEffect, useMemo, useState } from "react";
import { Info, Wrench } from "lucide-react";
import { applyPatches, type Corrections, type Rung } from "../../engine";

interface Props {
  rungs: Rung[];
  corrections: Corrections;
  onApply: (text: string) => void;
}

export function CorrectionsPanel({ rungs, corrections, onApply }: Props) {
  const { patches, advisories } = corrections;
  const [selected, setSelected] = useState<Set<string>>(() => new Set(patches.filter((p) => p.autoApplicable).map((p) => p.id)));
  useEffect(() => setSelected(new Set(patches.filter((p) => p.autoApplicable).map((p) => p.id))), [patches]);

  const preview = useMemo(() => {
    const chosen = patches.filter((p) => selected.has(p.id));
    return chosen.length ? applyPatches(rungs, chosen) : null;
  }, [patches, rungs, selected]);

  if (!patches.length && !advisories.length) {
    return <p className="py-10 text-center text-slate-400" style={{ fontSize: "0.85rem" }}>Nothing to correct.</p>;
  }

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-4">
      {patches.length > 0 && (
        <ul className="space-y-2.5">
          {patches.map((p) => (
            <li key={p.id} className="p-3.5 rounded-xl bg-slate-950 border border-slate-700/80">
              <label className="flex items-start gap-2.5 cursor-pointer">
                <input type="checkbox" checked={selected.has(p.id)} onChange={() => toggle(p.id)} className="mt-1 accent-cyan-500" />
                <span className="flex-1">
                  <span className="text-slate-100" style={{ fontSize: "0.84rem", fontWeight: 600 }}>{p.description}</span>
                  <span className="block text-slate-500" style={{ fontSize: "0.68rem" }}>
                    <span className="font-mono">{p.rule}</span> · rung{p.rungs.length > 1 ? "s" : ""} {p.rungs.join(", ")} ·{" "}
                    {p.autoApplicable ? "safe structural change" : "needs your confirmation (field wiring or intent)"}
                  </span>
                </span>
              </label>
              <div className="mt-2.5 grid md:grid-cols-2 gap-2">
                <div>
                  <p className="text-red-300/80 mb-1" style={{ fontSize: "0.66rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>Before</p>
                  <pre className="p-2 rounded-lg bg-red-500/5 border border-red-500/20 text-red-100/90 whitespace-pre-wrap break-all" style={{ fontSize: "0.7rem", fontFamily: "'Fira Code', monospace" }}>
                    {p.before.join("\n") || "(new rung)"}
                  </pre>
                </div>
                <div>
                  <p className="text-emerald-300/80 mb-1" style={{ fontSize: "0.66rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>After</p>
                  <pre className="p-2 rounded-lg bg-emerald-500/5 border border-emerald-500/20 text-emerald-100/90 whitespace-pre-wrap break-all" style={{ fontSize: "0.7rem", fontFamily: "'Fira Code', monospace" }}>
                    {p.after.join("\n") || "(rung removed)"}
                  </pre>
                </div>
              </div>
              {p.verification.length > 0 && (
                <details className="mt-2">
                  <summary className="text-slate-400 cursor-pointer" style={{ fontSize: "0.72rem" }}>How to verify ({p.verification.length} steps)</summary>
                  <ol className="mt-1 ml-4 list-decimal space-y-0.5 text-slate-400" style={{ fontSize: "0.72rem" }}>
                    {p.verification.map((v, i) => <li key={i}>{v}</li>)}
                  </ol>
                </details>
              )}
            </li>
          ))}
        </ul>
      )}

      {patches.length > 0 && (
        <div className="flex items-center justify-between gap-2 flex-wrap p-3 rounded-xl bg-slate-800/40 border border-slate-700">
          <p className="text-slate-400" style={{ fontSize: "0.75rem" }}>
            {selected.size} of {patches.length} selected.
            {preview && !preview.parse.ok && <span className="text-red-300"> The combined result does not parse; deselect a patch.</span>}
          </p>
          <button
            type="button"
            disabled={!preview || !preview.parse.ok}
            onClick={() => preview && onApply(preview.text)}
            className="flex items-center gap-2 px-3.5 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-800 disabled:text-slate-500 text-slate-950"
            style={{ fontSize: "0.8rem", fontWeight: 600 }}
          >
            <Wrench size={14} aria-hidden /> Load corrected program into the editor
          </button>
        </div>
      )}

      {advisories.length > 0 && (
        <section>
          <h3 className="flex items-center gap-1.5 text-slate-300 mb-2" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
            <Info size={14} aria-hidden /> Advice without a code change
          </h3>
          <ul className="space-y-1.5">
            {advisories.map((a) => (
              <li key={a.findingId} className="p-2.5 rounded-lg bg-slate-950 border border-slate-700/70 text-slate-300" style={{ fontSize: "0.76rem" }}>
                <span className="font-mono text-slate-500" style={{ fontSize: "0.66rem" }}>{a.rule}</span>
                <span className="block">{a.note}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
