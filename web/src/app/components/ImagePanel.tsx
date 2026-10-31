// Image -> program via the backend vision engine. The result is shown for review and handed to
// the text editor; nothing is analysed until the user accepts the recognised ladder text.

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Camera, CheckCircle2, ImageUp, Loader2, ServerOff, Wand2 } from "lucide-react";
import { api, friendlyMessage, type ProgramResponse } from "../lib/api";
import type { PlatformId } from "../lib/platforms";
import { useBackend, visionEnabled } from "../lib/useBackend";
import { STANDALONE } from "../lib/runtime";
import { BoundingBoxCanvas, type OverlayBox } from "./BoundingBoxCanvas";

const TYPES = ["image/png", "image/jpeg", "image/webp"];

/** Ladder text with rung labels, so recognised rung numbers survive the round trip. */
export function programTextFromResponse(res: ProgramResponse): string {
  const lines: string[] = [];
  for (const r of res.rungs) {
    if (r.comment) lines.push(...r.comment.split("\n").map((c) => `// ${c}`));
    lines.push(`${String(r.number).padStart(4, "0")}: ${r.text}`);
  }
  return lines.join("\n");
}

interface Props {
  platform: PlatformId;
  onRecognized: (text: string, res: ProgramResponse) => void;
}

export function ImagePanel({ platform, onRecognized }: Props) {
  const backend = useBackend();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProgramResponse | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const maxMb = backend.meta?.limits.upload_mb ?? 8;

  useEffect(() => () => {
    abortRef.current?.abort();
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  const accept = (f: File | undefined | null) => {
    setError(null);
    setResult(null);
    if (!f) return;
    if (!TYPES.includes(f.type)) {
      setError("Use a PNG, JPEG or WEBP image (screenshots and phone photos work).");
      return;
    }
    if (f.size > maxMb * 1024 * 1024) {
      setError(`The image is ${(f.size / 1024 / 1024).toFixed(1)} MB; the server accepts up to ${maxMb} MB.`);
      return;
    }
    if (preview) URL.revokeObjectURL(preview);
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const recognise = async () => {
    if (!file) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.parseImage(file, platform, ctrl.signal);
      setResult(res);
      if (!res.rungs.length) setError("No rungs were recognised. Try a sharper, straighter image or paste the ladder text instead.");
    } catch (e) {
      if (!ctrl.signal.aborted) setError(friendlyMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const boxes = useMemo<OverlayBox[]>(() => {
    if (!result) return [];
    const out: OverlayBox[] = [];
    for (const r of result.rungs) {
      for (const el of r.elements ?? []) {
        if (el.bbox) out.push({ bbox: el.bbox, label: el.mnemonic, confidence: el.confidence, kind: "instruction" });
      }
    }
    for (const d of result.detections ?? []) {
      if (/Rail|Branch/.test(d.class_name)) out.push({ bbox: d.bbox, label: d.class_name, kind: "structure" });
    }
    return out;
  }, [result]);

  const offline = backend.status === "offline";
  const noEngine = backend.status === "online" && !visionEnabled(backend);

  return (
    <div className="space-y-3">
      {(offline || noEngine) && (
        <div role="status" className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/5 border border-amber-500/25 text-amber-200/90" style={{ fontSize: "0.78rem" }}>
          <ServerOff size={15} className="mt-0.5 flex-shrink-0" aria-hidden />
          <span>
            {offline && STANDALONE
              ? "This is the standalone copy of LogicLens, so it has no recognition server. Paste the ladder text instead: all checks, the Structured Text and the simulator work here. For screenshots, run Start-LogicLens.cmd from the LogicLens-v2 folder."
              : offline
              ? "The LogicLens server is not reachable, so images can't be recognised right now. Paste the ladder text instead: all checks, the Structured Text and the simulator run in your browser."
              : "This server has no image-recognition engine configured (set LOGICLENS_YOLO_ONNX and/or ANTHROPIC_API_KEY)."}
          </span>
        </div>
      )}

      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); accept(e.dataTransfer.files?.[0]); }}
        className={`rounded-xl border-2 border-dashed p-5 text-center transition-colors ${dragOver ? "border-cyan-400 bg-cyan-500/5" : "border-slate-700 bg-slate-950/50"}`}
      >
        <ImageUp size={26} className="mx-auto text-slate-500" aria-hidden />
        <p className="text-slate-300 mt-2" style={{ fontSize: "0.85rem" }}>Drop a screenshot or photo of a ladder diagram</p>
        <p className="text-slate-500" style={{ fontSize: "0.72rem" }}>PNG, JPEG or WEBP, up to {maxMb} MB. Processed in memory and not stored.</p>
        <div className="mt-3 flex items-center justify-center gap-2 flex-wrap">
          <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700 cursor-pointer focus-within:ring-2 focus-within:ring-cyan-500" style={{ fontSize: "0.8rem" }}>
            <ImageUp size={14} aria-hidden /> Choose image
            <input type="file" accept={TYPES.join(",")} className="sr-only" onChange={(e) => { accept(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <label className="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 hover:bg-slate-700 cursor-pointer focus-within:ring-2 focus-within:ring-cyan-500 lg:hidden" style={{ fontSize: "0.8rem" }}>
            <Camera size={14} aria-hidden /> Take photo
            <input type="file" accept="image/*" capture="environment" className="sr-only" onChange={(e) => { accept(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
        </div>
      </div>

      {preview && (
        <div className="space-y-3">
          {result && boxes.length ? (
            <BoundingBoxCanvas imageSrc={preview} boxes={boxes} />
          ) : (
            <img src={preview} alt="Selected diagram" className="w-full max-h-80 object-contain rounded-xl border border-slate-700 bg-slate-950" />
          )}
          <button
            type="button"
            onClick={recognise}
            disabled={busy || offline || noEngine}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 disabled:bg-slate-800 disabled:text-slate-500 text-slate-950 disabled:cursor-not-allowed"
            style={{ fontWeight: 600, fontSize: "0.85rem" }}
          >
            {busy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Wand2 size={15} aria-hidden />}
            {busy ? "Recognising…" : "Recognise ladder logic"}
          </button>
        </div>
      )}

      <div aria-live="polite">
        {error && (
          <p role="alert" className="flex items-start gap-2 p-3 rounded-lg bg-red-500/5 border border-red-500/25 text-red-300" style={{ fontSize: "0.78rem" }}>
            <AlertTriangle size={14} className="mt-0.5 flex-shrink-0" aria-hidden /> {error}
          </p>
        )}
      </div>

      {result && result.rungs.length > 0 && (
        <div className="p-3 rounded-xl bg-slate-950 border border-slate-700 space-y-2">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="flex items-center gap-1.5 text-emerald-300" style={{ fontSize: "0.8rem", fontWeight: 500 }}>
              <CheckCircle2 size={14} aria-hidden /> {result.rungs.length} rung{result.rungs.length === 1 ? "" : "s"} recognised
            </span>
            <span className="text-slate-500" style={{ fontSize: "0.7rem" }}>
              {result.engine.name}
              {result.timing_ms?.total != null ? ` · ${Math.round(result.timing_ms.total)} ms` : ""}
              {result.image?.quality ? ` · image quality ${Math.round(result.image.quality.overall)}/100` : ""}
            </span>
          </div>
          {result.engine.name === "stub" && (
            <p role="alert" className="text-amber-300" style={{ fontSize: "0.75rem" }}>
              The server runs the stub engine: this is a fixed demo program, not a reading of your image.
            </p>
          )}
          <pre className="max-h-40 overflow-auto text-slate-300 whitespace-pre-wrap break-all" style={{ fontSize: "0.72rem", fontFamily: "'Fira Code', monospace" }}>
            {programTextFromResponse(result)}
          </pre>
          {result.warnings.length > 0 && (
            <ul className="space-y-0.5 text-amber-300/90" style={{ fontSize: "0.72rem" }}>
              {result.warnings.slice(0, 10).map((w, i) => <li key={i}>• {w}</li>)}
            </ul>
          )}
          <p className="text-slate-500" style={{ fontSize: "0.72rem" }}>
            Check the recognised text against the image ("?" marks operands that could not be read), then analyse.
          </p>
          <button
            type="button"
            onClick={() => onRecognized(programTextFromResponse(result), result)}
            className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-cyan-500/40 text-cyan-300 hover:bg-slate-700"
            style={{ fontSize: "0.82rem", fontWeight: 500 }}
          >
            Review in editor and analyse
          </button>
        </div>
      )}
    </div>
  );
}
