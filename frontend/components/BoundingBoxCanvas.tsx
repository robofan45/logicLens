'use client';

import { useEffect, useRef } from 'react';
import type { BoundingBox } from '@/lib/api';

// Color mapping by class name keywords
const CLASS_COLORS: Record<string, string> = {
  contact: '#3b82f6',
  coil: '#f97316',
  timer: '#22c55e',
  counter: '#a855f7',
  output: '#f97316',
  input: '#3b82f6',
  branch: '#eab308',
  rung: '#6b7280',
};

function colorForClass(className: string): string {
  const lower = className.toLowerCase();
  for (const [key, color] of Object.entries(CLASS_COLORS)) {
    if (lower.includes(key)) return color;
  }
  return '#94a3b8';
}

interface Props {
  imageUrl: string;
  detections: BoundingBox[];
  imageWidth: number;
  imageHeight: number;
}

export default function BoundingBoxCanvas({
  imageUrl,
  detections,
  imageWidth,
  imageHeight,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const img = new Image();
    img.src = imageUrl;
    img.onload = () => {
      // Scale canvas to container width while preserving aspect ratio
      const containerWidth = container.clientWidth;
      const scale = containerWidth / (imageWidth || img.naturalWidth);
      const scaledHeight = (imageHeight || img.naturalHeight) * scale;

      canvas.width = containerWidth;
      canvas.height = scaledHeight;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      ctx.drawImage(img, 0, 0, containerWidth, scaledHeight);

      detections.forEach((det) => {
        const color = colorForClass(det.class_name);
        const x = det.x1 * scale;
        const y = det.y1 * scale;
        const w = (det.x2 - det.x1) * scale;
        const h = (det.y2 - det.y1) * scale;

        // Box
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);

        // Label background
        const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
        ctx.font = 'bold 11px Inter, sans-serif';
        const textWidth = ctx.measureText(label).width;
        const labelH = 16;
        const labelY = y > labelH ? y - labelH : y;

        ctx.fillStyle = color;
        ctx.fillRect(x, labelY, textWidth + 6, labelH);

        // Label text
        ctx.fillStyle = '#ffffff';
        ctx.fillText(label, x + 3, labelY + 11);
      });
    };
  }, [imageUrl, detections, imageWidth, imageHeight]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400">
        Element Detections ({detections.length})
      </h3>
      <div ref={containerRef} className="w-full overflow-hidden rounded-lg">
        <canvas ref={canvasRef} className="w-full rounded-lg" />
      </div>

      {/* Legend */}
      {detections.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2">
          {[...new Set(detections.map((d) => d.class_name))].map((cls) => (
            <span
              key={cls}
              className="flex items-center gap-1 rounded-full px-2 py-0.5 text-xs text-white"
              style={{ backgroundColor: colorForClass(cls) + '55', border: `1px solid ${colorForClass(cls)}` }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: colorForClass(cls) }}
              />
              {cls}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
