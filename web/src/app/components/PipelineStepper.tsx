// Real pipeline stages with real timings (no simulated delays).

import { CheckCircle2, Circle, Loader2, MinusCircle, XCircle } from "lucide-react";

export type StageStatus = "pending" | "running" | "done" | "error" | "skipped";

export interface StageView {
  id: string;
  label: string;
  detail?: string;
  status: StageStatus;
  ms?: number;
}

const ICON = {
  pending: <Circle size={15} className="text-slate-600" aria-hidden />,
  running: <Loader2 size={15} className="text-cyan-400 animate-spin" aria-hidden />,
  done: <CheckCircle2 size={15} className="text-emerald-400" aria-hidden />,
  error: <XCircle size={15} className="text-red-400" aria-hidden />,
  skipped: <MinusCircle size={15} className="text-slate-600" aria-hidden />,
};

const fmt = (ms: number) => (ms < 1 ? "<1 ms" : ms < 1000 ? `${ms.toFixed(ms < 10 ? 1 : 0)} ms` : `${(ms / 1000).toFixed(2)} s`);

export function PipelineStepper({ stages }: { stages: StageView[] }) {
  return (
    <ol className="space-y-2" aria-label="Analysis pipeline">
      {stages.map((s) => (
        <li key={s.id} className="flex items-start gap-2.5">
          <span className="mt-0.5">{ICON[s.status]}</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between gap-2">
              <span className={s.status === "pending" || s.status === "skipped" ? "text-slate-500" : "text-slate-200"} style={{ fontSize: "0.8rem", fontWeight: 500 }}>
                {s.label}
                <span className="sr-only"> — {s.status}</span>
              </span>
              {s.ms != null && s.status === "done" && <span className="text-slate-500 font-mono" style={{ fontSize: "0.68rem" }}>{fmt(s.ms)}</span>}
            </div>
            {s.detail && <p className="text-slate-500 truncate" style={{ fontSize: "0.7rem" }} title={s.detail}>{s.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
