// Draws recognition boxes over the uploaded image. Boxes are [x1, y1, x2, y2] in source pixels
// (contract §2), so they are scaled to the displayed size.

import { useEffect, useRef, useState } from "react";

export interface OverlayBox {
  bbox: [number, number, number, number];
  label: string;
  confidence?: number | null;
  kind?: "instruction" | "structure";
}

interface Props {
  imageSrc: string;
  boxes: OverlayBox[];
  maxHeight?: number;
}

export function BoundingBoxCanvas({ imageSrc, boxes, maxHeight = 420 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !wrap || !ctx) return;
    let cancelled = false;
    setFailed(false);
    const img = new Image();
    img.onerror = () => !cancelled && setFailed(true);
    img.onload = () => {
      if (cancelled) return;
      const scale = Math.min(wrap.clientWidth / img.naturalWidth, maxHeight / img.naturalHeight, 1.5);
      canvas.width = Math.round(img.naturalWidth * scale);
      canvas.height = Math.round(img.naturalHeight * scale);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      ctx.font = "10px 'Fira Code', monospace";
      for (const b of boxes) {
        const [x1, y1, x2, y2] = b.bbox.map((v) => v * scale);
        const color = b.kind === "structure" ? "rgba(148,163,184,0.9)" : "rgba(34,211,238,0.95)";
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
        if (b.kind !== "structure") {
          const text = b.confidence != null ? `${b.label} ${Math.round(b.confidence)}%` : b.label;
          const tw = ctx.measureText(text).width + 6;
          ctx.fillStyle = "rgba(8,47,73,0.85)";
          ctx.fillRect(x1, Math.max(0, y1 - 13), tw, 13);
          ctx.fillStyle = "#e0f2fe";
          ctx.fillText(text, x1 + 3, Math.max(10, y1 - 3));
        }
      }
    };
    img.src = imageSrc;
    return () => {
      cancelled = true;
    };
  }, [imageSrc, boxes, maxHeight]);

  return (
    <div ref={wrapRef} className="w-full rounded-xl overflow-hidden border border-slate-700 bg-slate-950">
      {failed ? (
        <p className="p-6 text-center text-slate-500" style={{ fontSize: "0.8rem" }}>The image could not be displayed.</p>
      ) : (
        <canvas ref={canvasRef} role="img" aria-label={`Uploaded diagram with ${boxes.length} recognised elements`} className="block mx-auto max-w-full" />
      )}
    </div>
  );
}
