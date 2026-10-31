import { Download } from "lucide-react";
import type { StResult } from "../../engine";
import { downloadText, safeFileName } from "../lib/download";
import { CopyButton } from "./bits";

export function StPanel({ st, name }: { st: StResult; name: string }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-slate-500" style={{ fontSize: "0.74rem" }}>
          IEC 61131-3 Structured Text with the same scan semantics as the ladder (checked against the simulator in the test suite).
        </p>
        <div className="flex gap-2">
          <CopyButton text={st.code} />
          <button
            type="button"
            onClick={() => downloadText(safeFileName(name, "st"), st.code)}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700"
            style={{ fontSize: "0.75rem" }}
          >
            <Download size={13} aria-hidden /> .st
          </button>
        </div>
      </div>
      {st.warnings.length > 0 && (
        <ul className="p-2.5 rounded-lg bg-amber-500/5 border border-amber-500/20 space-y-0.5 text-amber-200/80" style={{ fontSize: "0.72rem" }}>
          {st.warnings.map((w, i) => <li key={i}>• {w}</li>)}
        </ul>
      )}
      <pre
        className="p-3 rounded-xl bg-slate-950 border border-slate-700 text-slate-200 overflow-auto max-h-[32rem]"
        style={{ fontSize: "0.74rem", lineHeight: 1.55, fontFamily: "'Fira Code', ui-monospace, monospace" }}
        aria-label="Generated Structured Text"
        tabIndex={0}
      >
        {st.code}
      </pre>
    </div>
  );
}
