import { useMemo, useState } from "react";
import { ArrowRight, Clock } from "lucide-react";
import type { Xref } from "../../engine";

const PHYS_STYLE: Record<string, string> = {
  input: "text-sky-300",
  output: "text-emerald-300",
  internal: "text-violet-300",
  unknown: "text-slate-400",
};

export function TracePanel({ xref }: { xref: Xref }) {
  const [query, setQuery] = useState("");
  const tags = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...xref.tags.values()]
      .filter((t) => !q || t.display.toLowerCase().includes(q))
      .sort((a, b) => a.display.localeCompare(b.display));
  }, [xref, query]);

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-slate-300 mb-2" style={{ fontSize: "0.82rem", fontWeight: 600 }}>What drives each output</h3>
        <p className="text-slate-500 mb-2" style={{ fontSize: "0.72rem" }}>
          Rung-condition at every output instruction, traced left to right through series contacts (AND) and branches (OR), the way the PLC scans it.
        </p>
        <ul className="space-y-1.5">
          {xref.outputs.map((o) => (
            <li key={o.instrId} className="p-2.5 rounded-lg bg-slate-950 border border-slate-700/70" style={{ fontSize: "0.76rem" }}>
              <span className="text-slate-500 font-mono">rung {o.rung} · {o.mnemonic}</span>
              <div className="mt-1 flex items-start gap-2 flex-wrap">
                <code className="text-emerald-300">{o.target ? xref.table.display(o.target) : o.mnemonic}</code>
                <ArrowRight size={13} className="text-slate-600 mt-0.5" aria-label="is driven by" />
                <code className="text-slate-200 break-all">{o.text}</code>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {xref.scanNotes.length > 0 && (
        <section>
          <h3 className="flex items-center gap-1.5 text-slate-300 mb-2" style={{ fontSize: "0.82rem", fontWeight: 600 }}>
            <Clock size={14} aria-hidden /> Scan-order notes
          </h3>
          <ul className="space-y-1">
            {xref.scanNotes.map((n, i) => (
              <li key={i} className="text-amber-200/80" style={{ fontSize: "0.74rem" }}>• {n.message}</li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
          <h3 className="text-slate-300" style={{ fontSize: "0.82rem", fontWeight: 600 }}>Cross-reference ({xref.tags.size} tags)</h3>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter tags…"
            aria-label="Filter tags"
            className="px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-cyan-500"
            style={{ fontSize: "0.75rem" }}
          />
        </div>
        <div className="overflow-x-auto rounded-xl border border-slate-700">
          <table className="w-full" style={{ fontSize: "0.74rem" }}>
            <thead>
              <tr className="bg-slate-800/60 text-slate-400 text-left">
                <th scope="col" className="px-3 py-2 font-medium">Tag</th>
                <th scope="col" className="px-3 py-2 font-medium">Kind</th>
                <th scope="col" className="px-3 py-2 font-medium">Read in rungs</th>
                <th scope="col" className="px-3 py-2 font-medium">Written in rungs</th>
              </tr>
            </thead>
            <tbody>
              {tags.slice(0, 500).map((t) => (
                <tr key={t.key} className="border-t border-slate-800">
                  <td className="px-3 py-1.5 font-mono text-slate-200 break-all">{t.display}</td>
                  <td className={`px-3 py-1.5 ${PHYS_STYLE[t.physical] ?? ""}`}>{t.instance ?? (t.memberOf ? "member" : t.physical)}</td>
                  <td className="px-3 py-1.5 text-slate-400">{[...new Set(t.reads.map((r) => r.rung))].join(", ") || "—"}</td>
                  <td className="px-3 py-1.5 text-slate-400">
                    {[...new Set(t.writes.map((w) => `${w.rung} (${w.mnemonic})`))].join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
