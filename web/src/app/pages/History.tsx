import { useState } from "react";
import { Link } from "react-router";
import { Clock, FileDown, Image as ImageIcon, Trash2, Type } from "lucide-react";
import { clearHistory, deleteHistoryEntry, loadHistory, type HistoryEntry } from "../lib/history";
import { downloadText } from "../lib/download";
import { platformLabel } from "../lib/platforms";
import { SEVERITY_ORDER, SEVERITY_STYLE } from "../components/bits";

const GRADE: Record<string, string> = { Healthy: "text-emerald-300", "Minor issues": "text-sky-300", "Needs attention": "text-amber-300", Critical: "text-red-300" };

export function History() {
  const [entries, setEntries] = useState<HistoryEntry[]>(() => loadHistory());
  const [confirmClear, setConfirmClear] = useState(false);

  const remove = (id: string) => {
    deleteHistoryEntry(id);
    setEntries(loadHistory());
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-slate-100" style={{ fontSize: "1.35rem", fontWeight: 700 }}>History</h1>
          <p className="text-slate-500 mt-0.5" style={{ fontSize: "0.82rem" }}>
            The last {entries.length ? entries.length : "50"} analyses, stored only in this browser. Images are never kept.
          </p>
        </div>
        {entries.length > 0 && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => downloadText("logiclens-history.json", JSON.stringify(entries, null, 2), "application/json")}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700"
              style={{ fontSize: "0.78rem" }}
            >
              <FileDown size={14} aria-hidden /> Export
            </button>
            {confirmClear ? (
              <span className="flex items-center gap-2" style={{ fontSize: "0.78rem" }}>
                <span className="text-slate-400">Delete all?</span>
                <button type="button" onClick={() => { clearHistory(); setEntries([]); setConfirmClear(false); }} className="px-3 py-2 rounded-lg bg-red-500 text-white">Delete</button>
                <button type="button" onClick={() => setConfirmClear(false)} className="px-3 py-2 rounded-lg bg-slate-800 text-slate-300">Cancel</button>
              </span>
            ) : (
              <button type="button" onClick={() => setConfirmClear(true)} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700" style={{ fontSize: "0.78rem" }}>
                <Trash2 size={14} aria-hidden /> Clear all
              </button>
            )}
          </div>
        )}
      </header>

      {entries.length === 0 ? (
        <div className="py-20 text-center rounded-xl bg-slate-900 border border-dashed border-slate-700">
          <Clock size={28} className="mx-auto text-slate-600" aria-hidden />
          <p className="mt-3 text-slate-300">No analyses yet</p>
          <Link to="/analyzer" className="mt-3 inline-block text-cyan-300 hover:text-cyan-200" style={{ fontSize: "0.85rem" }}>Open the analyzer</Link>
        </div>
      ) : (
        <ul className="space-y-2.5">
          {entries.map((e) => (
            <li key={e.id} className="p-4 rounded-xl bg-slate-900 border border-slate-700/80 flex items-start gap-4 flex-wrap">
              <div className="flex-1 min-w-[14rem]">
                <Link to={`/analyzer?h=${encodeURIComponent(e.id)}`} className="text-slate-100 hover:text-cyan-300" style={{ fontSize: "0.92rem", fontWeight: 600 }}>
                  {e.name}
                </Link>
                <p className="mt-0.5 flex items-center gap-2 text-slate-500 flex-wrap" style={{ fontSize: "0.72rem" }}>
                  {e.source === "image" ? <ImageIcon size={12} aria-label="from an image" /> : <Type size={12} aria-label="from text" />}
                  <time dateTime={e.createdAt}>{new Date(e.createdAt).toLocaleString()}</time>
                  <span>· {platformLabel(e.platform)}</span>
                  <span>· {e.rungs} rungs</span>
                </p>
                {e.topFindings.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-slate-400" style={{ fontSize: "0.74rem" }}>
                    {e.topFindings.slice(0, 3).map((t, i) => <li key={i} className="truncate">• {t}</li>)}
                  </ul>
                )}
              </div>
              <div className="text-right">
                <p className={GRADE[e.grade] ?? "text-slate-300"} style={{ fontSize: "1.3rem", fontWeight: 800 }}>{e.riskScore}</p>
                <p className="text-slate-500" style={{ fontSize: "0.68rem" }}>{e.grade || "risk"}</p>
                <div className="mt-1.5 flex gap-1 justify-end">
                  {SEVERITY_ORDER.map((s) => e.counts[s] > 0 && (
                    <span key={s} className={`px-1.5 rounded border ${SEVERITY_STYLE[s]}`} style={{ fontSize: "0.62rem" }} title={`${e.counts[s]} ${s}`}>{e.counts[s]}</span>
                  ))}
                </div>
              </div>
              <button type="button" onClick={() => remove(e.id)} aria-label={`Delete ${e.name}`} className="p-2 rounded-lg text-slate-500 hover:text-red-300 hover:bg-slate-800">
                <Trash2 size={15} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
