// Optional Claude layer through the backend: plain-language explanation and follow-up chat.
// Everything here is AI-generated and advisory; all text is rendered as plain text.

import { useRef, useState } from "react";
import { Bot, Loader2, Send, Sparkles } from "lucide-react";
import type { Finding } from "../../engine";
import { api, friendlyMessage, type ChatTurn, type ExplainResponse } from "../lib/api";
import type { PlatformId } from "../lib/platforms";
import { llmEnabled, useBackend } from "../lib/useBackend";
import { STANDALONE } from "../lib/runtime";
import { SeverityBadge } from "./bits";

interface Props {
  programText: string;
  platform: PlatformId;
  context: string;
  findings: Finding[];
}

export function AiPanel({ programText, platform, context, findings }: Props) {
  const backend = useBackend();
  const enabled = llmEnabled(backend);
  const [explain, setExplain] = useState<ExplainResponse | null>(null);
  const [busy, setBusy] = useState<"explain" | "chat" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [question, setQuestion] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const run = async (depth: "standard" | "deep") => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBusy("explain");
    setError(null);
    try {
      const res = await api.explain(
        {
          program_text: programText,
          platform,
          user_context: context || undefined,
          depth,
          findings: findings.slice(0, 100).map((f) => ({
            id: f.id, rule: f.rule, severity: f.severity, title: f.title.slice(0, 200),
            description: f.description.slice(0, 2000), recommendation: f.recommendation.slice(0, 2000), rungs: f.rungs.slice(0, 64),
          })),
        },
        ctrl.signal,
      );
      setExplain(res);
    } catch (e) {
      if (!ctrl.signal.aborted) setError(friendlyMessage(e));
    } finally {
      setBusy(null);
    }
  };

  const ask = async () => {
    const q = question.trim();
    if (!q || busy) return;
    setBusy("chat");
    setError(null);
    try {
      const res = await api.chat({ program_text: programText, question: q.slice(0, 4000), history: history.slice(-20) });
      setHistory((h) => [...h, { role: "user" as const, content: q }, { role: "assistant" as const, content: res.answer }].slice(-20));
      setQuestion("");
    } catch (e) {
      setError(friendlyMessage(e));
    } finally {
      setBusy(null);
    }
  };

  if (!enabled) {
    return (
      <div className="py-8 px-4 text-center space-y-2">
        <Bot size={28} className="mx-auto text-slate-600" aria-hidden />
        <p className="text-slate-300" style={{ fontSize: "0.85rem" }}>AI explanations are not available right now.</p>
        <p className="text-slate-500 max-w-md mx-auto" style={{ fontSize: "0.76rem" }}>
          {STANDALONE
            ? "This standalone copy has no server."
            : backend.status === "offline"
            ? "The LogicLens server is not reachable."
            : "The server needs an Anthropic API key (ANTHROPIC_API_KEY) for this tab."}{" "}
          Every other tab works without it: the checks, Structured Text and simulator run in your browser.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <button type="button" onClick={() => run("standard")} disabled={!!busy} className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-violet-500 hover:bg-violet-400 disabled:opacity-50 text-white" style={{ fontSize: "0.8rem", fontWeight: 600 }}>
          {busy === "explain" ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Sparkles size={14} aria-hidden />} Explain this program
        </button>
        <button type="button" onClick={() => run("deep")} disabled={!!busy} className="px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 disabled:opacity-50" style={{ fontSize: "0.78rem" }}>
          Deep review (slower)
        </button>
        <span className="text-slate-500" style={{ fontSize: "0.7rem" }}>The program text and findings are sent to the server, which calls Claude. Images are not sent.</span>
      </div>

      {error && <p role="alert" className="p-2.5 rounded-lg bg-red-500/5 border border-red-500/25 text-red-300" style={{ fontSize: "0.78rem" }}>{error}</p>}

      {explain && (
        <div className="space-y-3">
          <section className="p-3.5 rounded-xl bg-violet-500/5 border border-violet-500/20">
            <p className="text-violet-300 mb-1" style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.05em" }}>AI summary · {explain.model}</p>
            <p className="text-slate-200 whitespace-pre-wrap" style={{ fontSize: "0.8rem", lineHeight: 1.55 }}>{explain.summary}</p>
          </section>
          {explain.rung_explanations.length > 0 && (
            <ul className="space-y-1.5">
              {explain.rung_explanations.map((r, i) => (
                <li key={i} className="p-2.5 rounded-lg bg-slate-950 border border-slate-700/70" style={{ fontSize: "0.76rem" }}>
                  <span className="text-slate-500 font-mono">rung {r.rung}</span>
                  <p className="text-slate-300 whitespace-pre-wrap">{r.text}</p>
                </li>
              ))}
            </ul>
          )}
          {explain.ai_findings.length > 0 && (
            <section>
              <h3 className="text-slate-300 mb-1.5" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Extra observations from the AI (not rule-checked)</h3>
              <ul className="space-y-2">
                {explain.ai_findings.map((f, i) => (
                  <li key={i} className="p-3 rounded-xl bg-slate-950 border border-violet-500/20">
                    <div className="flex items-center gap-2 flex-wrap">
                      <SeverityBadge severity={f.severity} />
                      <span className="text-slate-100" style={{ fontSize: "0.82rem", fontWeight: 600 }}>{f.title}</span>
                      {f.rungs.length > 0 && <span className="text-slate-500" style={{ fontSize: "0.68rem" }}>rungs {f.rungs.join(", ")}</span>}
                    </div>
                    <p className="mt-1 text-slate-300 whitespace-pre-wrap" style={{ fontSize: "0.76rem" }}>{f.description}</p>
                    {f.recommendation && <p className="mt-1 text-emerald-200/80 whitespace-pre-wrap" style={{ fontSize: "0.74rem" }}>{f.recommendation}</p>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <p className="text-slate-500" style={{ fontSize: "0.7rem" }}>{explain.disclaimer}</p>
        </div>
      )}

      <section className="p-3 rounded-xl bg-slate-950 border border-slate-700/70 space-y-2">
        <h3 className="text-slate-300" style={{ fontSize: "0.8rem", fontWeight: 600 }}>Ask about this program</h3>
        {history.length > 0 && (
          <ul className="space-y-2 max-h-72 overflow-y-auto" aria-live="polite">
            {history.map((t, i) => (
              <li key={i} className={t.role === "user" ? "text-cyan-200" : "text-slate-300"} style={{ fontSize: "0.77rem" }}>
                <span className="text-slate-500" style={{ fontSize: "0.66rem" }}>{t.role === "user" ? "You" : "LogicLens AI"}</span>
                <p className="whitespace-pre-wrap">{t.content}</p>
              </li>
            ))}
          </ul>
        )}
        <form
          onSubmit={(e) => { e.preventDefault(); void ask(); }}
          className="flex gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={4000}
            placeholder="e.g. What happens if OL_Relay is stuck high?"
            aria-label="Question about the program"
            className="flex-1 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-500 focus:outline-none focus:border-violet-500"
            style={{ fontSize: "0.78rem" }}
          />
          <button type="submit" disabled={!question.trim() || !!busy} aria-label="Send question" className="px-3 py-2 rounded-lg bg-violet-500 disabled:opacity-40 text-white">
            {busy === "chat" ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Send size={15} aria-hidden />}
          </button>
        </form>
      </section>
    </div>
  );
}
