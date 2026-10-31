import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import {
  AlertTriangle, Binary, Bot, Code2, Cpu, FileDown, GitBranch, Image as ImageIcon, KeyRound, LayoutDashboard,
  Loader2, Play, RefreshCw, Settings2, Type, Workflow, Wrench,
} from "lucide-react";
import { analyzeProgram, exprToString, parseProgram, type Analysis, type Severity } from "../../engine";
import { AiPanel } from "../components/AiPanel";
import { Card, SEVERITY_ORDER, TabPanel, Tabs, type TabDef } from "../components/bits";
import { CorrectionsPanel } from "../components/CorrectionsPanel";
import { FaultList } from "../components/FaultList";
import { ImagePanel } from "../components/ImagePanel";
import { LadderDiagram } from "../components/LadderDiagram";
import { OverviewPanel } from "../components/OverviewPanel";
import { PipelineStepper, type StageView } from "../components/PipelineStepper";
import { ProgramEditor } from "../components/ProgramEditor";
import { SimulatorPanel } from "../components/SimulatorPanel";
import { StPanel } from "../components/StPanel";
import { TracePanel } from "../components/TracePanel";
import { apiKey, type ProgramResponse } from "../lib/api";
import { downloadText, safeFileName } from "../lib/download";
import { getHistoryEntry, newId, saveToHistory } from "../lib/history";
import { PLATFORMS, isPlatformId, type PlatformId } from "../lib/platforms";
import { buildReport } from "../lib/report";
import { getSample, SAMPLES } from "../lib/samples";
import { useBackend } from "../lib/useBackend";

type ResultTab = "overview" | "ladder" | "trace" | "faults" | "corrections" | "st" | "simulator" | "ai";
type InputMode = "text" | "image";

interface Analyzed {
  text: string;
  platform: PlatformId;
  source: "text" | "image";
  at: string;
}

const SEV_RANK: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1 };
const SEV_COLOR: Record<Severity, string> = { critical: "#ef4444", high: "#f97316", medium: "#f59e0b", low: "#60a5fa" };

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

export function Analyzer() {
  const [params] = useSearchParams();
  const initial = useMemo(() => {
    const h = params.get("h");
    const entry = h ? getHistoryEntry(h) : undefined;
    if (entry) return { text: entry.text, name: entry.name, platform: entry.platform, auto: true, source: entry.source };
    const sample = getSample(params.get("sample")) ?? SAMPLES[0];
    return { text: sample.text, name: sample.name, platform: sample.platform, auto: params.has("sample"), source: "text" as const };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const backend = useBackend();
  const [mode, setMode] = useState<InputMode>("text");
  const [text, setText] = useState(initial.text);
  const [name, setName] = useState(initial.name);
  const [platform, setPlatform] = useState<PlatformId>(initial.platform);
  const [context, setContext] = useState("");
  const [source, setSource] = useState<"text" | "image">(initial.source);
  const [recognition, setRecognition] = useState<ProgramResponse | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [analyzed, setAnalyzed] = useState<Analyzed | null>(null);
  const [running, setRunning] = useState(false);
  const [tab, setTab] = useState<ResultTab>("overview");
  const [selected, setSelected] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [keyDraft, setKeyDraft] = useState(apiKey.get());
  const [saveNote, setSaveNote] = useState<string | null>(null);

  const debounced = useDebounced(text, 250);
  const liveErrors = useMemo(() => parseProgram(debounced).errors, [debounced]);

  const run = useCallback(
    // programName: pass it when the name changes in the same event (state updates land after this call)
    (programText: string, src: "text" | "image", plat: PlatformId, programName: string = name) => {
      setRunning(true);
      // let the spinner paint before the (synchronous, usually < 50 ms) analysis
      setTimeout(() => {
        const a = analyzeProgram(programText, {
          platform: plat,
          context,
          programName,
          generatedAt: new Date().toISOString().slice(0, 10),
          now: () => performance.now(),
        });
        const at = new Date().toISOString();
        setAnalysis(a);
        setAnalyzed({ text: programText, platform: plat, source: src, at });
        setSelected(null);
        setTab("overview");
        setRunning(false);
        if (a.parse.rungs.length) {
          const ok = saveToHistory({
            id: newId(),
            name: programName.trim() || "Untitled analysis",
            createdAt: at,
            platform: plat,
            source: src,
            text: programText,
            rungs: a.stats.rungs,
            riskScore: a.faults.riskScore,
            grade: a.faults.grade,
            counts: { critical: a.faults.counts.critical, high: a.faults.counts.high, medium: a.faults.counts.medium, low: a.faults.counts.low },
            topFindings: a.faults.findings.slice(0, 5).map((f) => f.title),
          });
          setSaveNote(ok ? null : "History could not be saved in this browser (storage blocked or full).");
        }
      }, 0);
    },
    [context, name],
  );

  useEffect(() => {
    if (initial.auto) run(initial.text, initial.source, initial.platform);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onRecognized = (programText: string, res: ProgramResponse, fileName?: string) => {
    const plat = res.platform !== "unknown" ? res.platform : platform;
    setText(programText);
    const imageName = fileName ? `Image: ${fileName.slice(0, 80)}` : "Recognised image";
    setName(imageName);
    setSource("image");
    setRecognition(res);
    setPlatform(plat);
    setMode("text");
    run(programText, "image", plat, imageName);
  };

  const loadSample = (id: string) => {
    const s = getSample(id);
    if (!s) return;
    setText(s.text);
    setName(s.name);
    setPlatform(s.platform);
    setSource("text");
    setRecognition(null);
  };

  const highlights = useMemo(() => {
    const out: Record<string, Severity> = {};
    for (const f of analysis?.faults.findings ?? []) {
      for (const id of f.instrIds) if (!out[id] || SEV_RANK[f.severity] > SEV_RANK[out[id]]) out[id] = f.severity;
    }
    return out;
  }, [analysis]);

  const stale = analyzed !== null && (analyzed.text !== text || analyzed.platform !== platform);
  const ok = !!analysis && analysis.parse.rungs.length > 0;

  const stages: StageView[] = useMemo(() => {
    const t = analysis?.timingsMs;
    const st = (done: boolean) => (running ? "running" : done ? "done" : "pending") as StageView["status"];
    const recog: StageView =
      analyzed?.source === "image" && recognition
        ? { id: "recognize", label: "Recognise image", status: "done", ms: recognition.timing_ms?.total, detail: `${recognition.engine.name}, ${recognition.rungs.length} rungs` }
        : { id: "recognize", label: "Recognise image", status: "skipped", detail: "text input" };
    if (!analysis) return [recog, ...["Parse ladder text", "Trace signal flow", "Run checks", "Suggest corrections", "Generate Structured Text"].map((label, i) => ({ id: `s${i}`, label, status: st(false) }))];
    const p = analysis.parse;
    return [
      recog,
      { id: "parse", label: "Parse ladder text", status: p.rungs.length ? "done" : "error", ms: t?.parse, detail: `${p.rungs.length} rungs${p.errors.length ? `, ${p.errors.length} error${p.errors.length > 1 ? "s" : ""}` : ""}` },
      { id: "trace", label: "Trace signal flow", status: ok ? "done" : "skipped", ms: t?.xref, detail: ok ? `${analysis.xref.tags.size} tags, ${analysis.xref.outputs.length} outputs` : undefined },
      { id: "checks", label: "Run checks", status: ok ? "done" : "skipped", ms: t?.faults, detail: ok ? `${analysis.faults.findings.length} findings, risk ${analysis.faults.riskScore}` : undefined },
      { id: "fix", label: "Suggest corrections", status: ok ? "done" : "skipped", ms: t?.corrections, detail: ok ? `${analysis.corrections.patches.length} patches` : undefined },
      { id: "st", label: "Generate Structured Text", status: ok ? "done" : "skipped", ms: t?.st, detail: ok ? `${analysis.st.code.split("\n").length} lines` : undefined },
    ];
  }, [analysis, analyzed, recognition, running, ok]);

  const tabs: TabDef<ResultTab>[] = [
    { id: "overview", label: "Overview", icon: <LayoutDashboard size={13} aria-hidden /> },
    { id: "ladder", label: "Diagram", icon: <Binary size={13} aria-hidden /> },
    { id: "trace", label: "Signal trace", icon: <GitBranch size={13} aria-hidden /> },
    { id: "faults", label: "Findings", icon: <AlertTriangle size={13} aria-hidden />, badge: analysis?.faults.findings.length },
    { id: "corrections", label: "Corrections", icon: <Wrench size={13} aria-hidden /> },
    { id: "st", label: "Structured Text", icon: <Code2 size={13} aria-hidden /> },
    { id: "simulator", label: "Simulator", icon: <Play size={13} aria-hidden /> },
    { id: "ai", label: "AI explain", icon: <Bot size={13} aria-hidden /> },
  ];

  const selectedInfo = selected && analysis ? analysis.xref.instructions.get(selected) : undefined;
  const selectedFindings = selected && analysis ? analysis.faults.findings.filter((f) => f.instrIds.includes(selected)) : [];

  const exportReport = () => {
    if (!analysis || !analyzed) return;
    downloadText(
      safeFileName(name, "md"),
      buildReport({ name, platform: analyzed.platform, generatedAt: analyzed.at, programText: analyzed.text, analysis, source: analyzed.source }),
      "text/markdown",
    );
  };
  const exportJson = () => {
    if (!analysis || !analyzed) return;
    const { faults, stats, corrections, st } = analysis;
    downloadText(
      safeFileName(name, "json"),
      JSON.stringify({ tool: "LogicLens", version: 2, name, generatedAt: analyzed.at, platform: analyzed.platform, program: analyzed.text, stats, riskScore: faults.riskScore, grade: faults.grade, counts: faults.counts, findings: faults.findings, checklist: faults.checklist, corrections, structuredText: st.code }, null, 2),
      "application/json",
    );
  };

  return (
    <div className="min-h-full bg-slate-950">
      <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">
        <header className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-slate-100" style={{ fontSize: "1.35rem", fontWeight: 700, letterSpacing: "-0.02em" }}>Ladder logic analyzer</h1>
            <p className="text-slate-500 mt-0.5" style={{ fontSize: "0.82rem" }}>
              Paste ladder text or recognise a screenshot, then get checks, a signal trace, corrections, Structured Text and a live simulator.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowSettings((s) => !s)}
            aria-expanded={showSettings}
            aria-controls="analysis-settings"
            className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700"
            style={{ fontSize: "0.8rem" }}
          >
            <Settings2 size={15} aria-hidden /> Analysis settings
          </button>
        </header>

        {showSettings && (
          <Card className="space-y-0">
            <div id="analysis-settings" className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
              <label className="block" style={{ fontSize: "0.75rem" }}>
                <span className="text-slate-400 block mb-1.5">Program name</span>
                <input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 focus:outline-none focus:border-cyan-500" />
              </label>
              <label className="block" style={{ fontSize: "0.75rem" }}>
                <span className="text-slate-400 block mb-1.5">Context for the AI (optional)</span>
                <input value={context} maxLength={4000} onChange={(e) => setContext(e.target.value)} placeholder="e.g. conveyor sorting line, area 3" className="w-full px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500" />
              </label>
              <label className="block" style={{ fontSize: "0.75rem" }}>
                <span className="text-slate-400 flex items-center gap-1.5 mb-1.5"><KeyRound size={12} aria-hidden /> Server API key (if required)</span>
                <span className="flex gap-2">
                  <input type="password" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} autoComplete="off" className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 focus:outline-none focus:border-cyan-500" />
                  <button type="button" onClick={() => { apiKey.set(keyDraft); void backend.refresh(); }} className="px-3 py-2 rounded-lg bg-slate-700 text-slate-200">Save</button>
                </span>
                <span className="text-slate-600 block mt-1">Kept for this browser tab only.</span>
              </label>
              <div style={{ fontSize: "0.75rem" }}>
                <span className="text-slate-400 block mb-1.5">Server</span>
                <p className="text-slate-300">
                  {backend.status === "checking" ? "Checking…" : backend.status === "online" ? `Online · v${backend.health?.version ?? "?"}` : "Offline"}
                  {backend.meta && ` · vision: ${backend.meta.engines.active ?? "none"} · AI: ${backend.meta.llm.enabled ? "on" : "off"}`}
                </p>
                <button type="button" onClick={() => void backend.refresh()} className="mt-1.5 flex items-center gap-1.5 text-cyan-300 hover:text-cyan-200">
                  <RefreshCw size={12} aria-hidden /> Check again
                </button>
              </div>
            </div>
          </Card>
        )}

        <div className="grid lg:grid-cols-5 gap-5">
          <div className="lg:col-span-2 space-y-5 min-w-0">
            <Card>
              <Tabs<InputMode>
                label="Input"
                idPrefix="input"
                active={mode}
                onChange={setMode}
                tabs={[
                  { id: "text", label: "Ladder text", icon: <Type size={13} aria-hidden /> },
                  { id: "image", label: "Image", icon: <ImageIcon size={13} aria-hidden /> },
                ]}
              />
              <div className="mt-3">
                <TabPanel id="text" idPrefix="input" active={mode === "text"}>
                  <ProgramEditor
                    value={text}
                    onChange={(t) => setText(t)}
                    errors={liveErrors}
                    onSubmit={() => run(text, source, platform)}
                    onLoadSample={loadSample}
                    disabled={running}
                  />
                </TabPanel>
                <TabPanel id="image" idPrefix="input" active={mode === "image"}>
                  <ImagePanel platform={platform} onRecognized={onRecognized} />
                </TabPanel>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <select
                  aria-label="PLC platform"
                  value={platform}
                  onChange={(e) => isPlatformId(e.target.value) && setPlatform(e.target.value)}
                  className="flex-1 min-w-0 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 focus:outline-none focus:border-cyan-500"
                  style={{ fontSize: "0.78rem" }}
                >
                  {PLATFORMS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                </select>
                <button
                  type="button"
                  onClick={() => run(text, source, platform)}
                  disabled={running || !text.trim()}
                  className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-800 disabled:text-slate-500 text-slate-950"
                  style={{ fontWeight: 600, fontSize: "0.85rem" }}
                >
                  {running ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Cpu size={15} aria-hidden />}
                  {running ? "Analysing…" : "Analyse"}
                </button>
              </div>
              {stale && (
                <p className="mt-2 text-amber-300/90" style={{ fontSize: "0.72rem" }} role="status">
                  The program or platform changed since the last analysis. Analyse again to update the results.
                </p>
              )}
            </Card>

            <Card title="Pipeline" icon={<Workflow size={15} className="text-cyan-400" aria-hidden />}>
              <PipelineStepper stages={stages} />
              {saveNote && <p className="mt-2 text-amber-300/80" style={{ fontSize: "0.7rem" }}>{saveNote}</p>}
            </Card>
          </div>

          <div className="lg:col-span-3 min-w-0">
            {!analysis ? (
              <div className="h-full min-h-72 flex flex-col items-center justify-center gap-3 py-16 px-4 text-center rounded-xl bg-slate-900 border border-dashed border-slate-700">
                <Cpu size={30} className="text-slate-600" aria-hidden />
                <p className="text-slate-300" style={{ fontWeight: 500 }}>Results appear here</p>
                <p className="text-slate-500 max-w-sm" style={{ fontSize: "0.8rem" }}>
                  The example on the left is a real program with real mistakes in it. Press Analyse, or load one of the other examples.
                </p>
              </div>
            ) : (
              <Card
                actions={
                  ok ? (
                    <>
                      <button type="button" onClick={exportReport} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700" style={{ fontSize: "0.74rem" }}>
                        <FileDown size={13} aria-hidden /> Report (.md)
                      </button>
                      <button type="button" onClick={exportJson} className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700" style={{ fontSize: "0.74rem" }}>
                        <FileDown size={13} aria-hidden /> JSON
                      </button>
                    </>
                  ) : undefined
                }
                title={<span>Results <span className="text-slate-500" style={{ fontWeight: 400 }}>· {name}</span></span>}
              >
                {!ok ? (
                  <div role="alert" className="py-10 text-center space-y-2">
                    <AlertTriangle size={26} className="mx-auto text-red-400" aria-hidden />
                    <p className="text-red-300" style={{ fontSize: "0.88rem" }}>No valid rungs to analyse.</p>
                    <p className="text-slate-500" style={{ fontSize: "0.78rem" }}>Fix the errors listed under the editor and analyse again.</p>
                  </div>
                ) : (
                  <>
                    {analysis.parse.errors.length > 0 && (
                      <p role="status" className="mb-3 p-2.5 rounded-lg bg-red-500/5 border border-red-500/25 text-red-300" style={{ fontSize: "0.75rem" }}>
                        {analysis.parse.errors.length} rung{analysis.parse.errors.length > 1 ? "s" : ""} could not be parsed and {analysis.parse.errors.length > 1 ? "were" : "was"} left out. See the editor for details.
                      </p>
                    )}
                    <Tabs<ResultTab> label="Results" idPrefix="res" active={tab} onChange={setTab} tabs={tabs} />
                    <div className="mt-4">
                      <TabPanel id="overview" idPrefix="res" active={tab === "overview"}>
                        <OverviewPanel analysis={analysis} />
                      </TabPanel>
                      <TabPanel id="ladder" idPrefix="res" active={tab === "ladder"}>
                        <div className="space-y-3">
                          <div className="flex items-center gap-3 flex-wrap text-slate-500" style={{ fontSize: "0.7rem" }}>
                            <span>Dashed outline = instruction named in a finding. Click an instruction for its details.</span>
                            {SEVERITY_ORDER.filter((s) => Object.values(highlights).includes(s)).map((s) => (
                              <span key={s} className="flex items-center gap-1 capitalize">
                                <span className="w-2.5 h-2.5 rounded-sm border border-dashed" style={{ borderColor: SEV_COLOR[s], background: `${SEV_COLOR[s]}22` }} aria-hidden />
                                {s}
                              </span>
                            ))}
                          </div>
                          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                            <LadderDiagram rungs={analysis.parse.rungs} highlights={highlights} selectedId={selected} onSelect={setSelected} idPrefix="main" />
                          </div>
                          {selectedInfo && (
                            <div className="p-3 rounded-xl bg-slate-950 border border-cyan-500/30 space-y-1.5" style={{ fontSize: "0.76rem" }} aria-live="polite">
                              <p className="text-slate-200 font-mono">
                                rung {selectedInfo.rung}: {selectedInfo.instr.mnemonic}({selectedInfo.instr.operands.map((o) => o.raw).join(",")})
                              </p>
                              <p className="text-slate-400">Power reaches it when: <code className="text-slate-200">{exprToString(selectedInfo.conditionIn)}</code></p>
                              {selectedFindings.map((f) => <p key={f.id} className="text-amber-200/90">• {f.title}</p>)}
                            </div>
                          )}
                        </div>
                      </TabPanel>
                      <TabPanel id="trace" idPrefix="res" active={tab === "trace"}>
                        <TracePanel xref={analysis.xref} />
                      </TabPanel>
                      <TabPanel id="faults" idPrefix="res" active={tab === "faults"}>
                        <FaultList findings={analysis.faults.findings} onLocate={(id) => { setSelected(id); setTab("ladder"); }} />
                      </TabPanel>
                      <TabPanel id="corrections" idPrefix="res" active={tab === "corrections"}>
                        <CorrectionsPanel
                          rungs={analysis.parse.rungs}
                          corrections={analysis.corrections}
                          onApply={(t) => { setText(t); setSource("text"); setMode("text"); run(t, "text", platform); }}
                        />
                      </TabPanel>
                      <TabPanel id="st" idPrefix="res" active={tab === "st"}>
                        <StPanel st={analysis.st} name={name} />
                      </TabPanel>
                      <TabPanel id="simulator" idPrefix="res" active={tab === "simulator"}>
                        <SimulatorPanel rungs={analysis.parse.rungs} />
                      </TabPanel>
                      <TabPanel id="ai" idPrefix="res" active={tab === "ai"}>
                        <AiPanel programText={analyzed?.text ?? text} platform={analyzed?.platform ?? platform} context={context} findings={analysis.faults.findings} />
                      </TabPanel>
                    </div>
                  </>
                )}
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
