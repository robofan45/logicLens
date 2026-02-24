'use client';

import { useCallback, useState } from 'react';
import { FileText, Download } from 'lucide-react';
import type { ParseResponse, TraceResponse, FaultsResponse, CorrectionResponse } from '@/lib/api';

interface Props {
  parseResult: ParseResponse | null;
  traceResult: TraceResponse | null;
  faultsResult: FaultsResponse | null;
  correctionResult: CorrectionResponse | null;
  uploadedImage: string | null;
}

export default function ReportGenerator({
  parseResult,
  traceResult,
  faultsResult,
  correctionResult,
  uploadedImage,
}: Props) {
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generateReport = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const [html2canvas, { jsPDF }] = await Promise.all([
        import('html2canvas').then((m) => m.default),
        import('jspdf'),
      ]);

      // Build HTML report content
      const reportEl = document.createElement('div');
      reportEl.style.cssText = 'width:900px;padding:40px;background:#0f172a;color:#e2e8f0;font-family:Inter,sans-serif;';
      reportEl.innerHTML = buildReportHtml({
        parseResult,
        traceResult,
        faultsResult,
        correctionResult,
        uploadedImage,
      });

      document.body.appendChild(reportEl);
      const canvas = await html2canvas(reportEl, { useCORS: true, scale: 1.5, backgroundColor: '#0f172a' });
      document.body.removeChild(reportEl);

      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF({ orientation: 'portrait', unit: 'px', format: 'a4' });
      const pageW = pdf.internal.pageSize.getWidth();
      const pageH = pdf.internal.pageSize.getHeight();
      const imgH = (canvas.height * pageW) / canvas.width;
      let y = 0;
      while (y < imgH) {
        pdf.addImage(imgData, 'PNG', 0, -y, pageW, imgH);
        y += pageH;
        if (y < imgH) pdf.addPage();
      }
      const sessionId = parseResult?.session_id ?? 'report';
      pdf.save(`logiclens-report-${sessionId.slice(0, 8)}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Report generation failed');
    } finally {
      setGenerating(false);
    }
  }, [parseResult, traceResult, faultsResult, correctionResult, uploadedImage]);

  const hasData = parseResult || traceResult || faultsResult || correctionResult;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <FileText size={18} className="text-indigo-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          Analysis Report
        </h2>
      </div>

      <p className="mb-4 text-sm text-gray-500">
        Generate a comprehensive PDF report combining all analysis stages.
      </p>

      {error && (
        <div className="mb-3 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      <button
        onClick={generateReport}
        disabled={!hasData || generating}
        className="flex items-center gap-2 rounded-lg bg-indigo-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Download size={14} />
        {generating ? 'Generating…' : 'Generate PDF Report'}
      </button>
    </div>
  );
}

function buildReportHtml({
  parseResult,
  traceResult,
  faultsResult,
  correctionResult,
  uploadedImage,
}: Props): string {
  const ts = new Date().toLocaleString();
  let html = `
    <h1 style="color:#60a5fa;font-size:28px;margin-bottom:4px;">LogicLens Analysis Report</h1>
    <p style="color:#6b7280;font-size:13px;margin-bottom:32px;">Generated: ${ts}</p>
  `;

  if (uploadedImage) {
    html += `<img src="${uploadedImage}" style="max-width:100%;border-radius:8px;margin-bottom:24px;" />`;
  }

  if (parseResult) {
    html += `
      <h2 style="color:#93c5fd;font-size:18px;margin-top:24px;">Element Recognition</h2>
      <p>Session ID: <code style="color:#a78bfa;">${parseResult.session_id}</code></p>
      <p>Elements: ${parseResult.parsed_elements.length} · Rungs: ${parseResult.total_rungs} · Detections: ${parseResult.yolo_detections.length}</p>
      <p>Blur score: ${parseResult.blur_score.toFixed(2)} · Processing: ${parseResult.processing_time_ms} ms</p>
    `;
  }

  if (traceResult) {
    html += `
      <h2 style="color:#93c5fd;font-size:18px;margin-top:24px;">Signal Flow</h2>
      <p>Signal paths: ${traceResult.signal_paths.length} · Energized: ${traceResult.signal_paths.filter((s) => s.is_energized).length}</p>
    `;
  }

  if (faultsResult) {
    html += `
      <h2 style="color:#93c5fd;font-size:18px;margin-top:24px;">Fault Analysis</h2>
      <p>Overall risk score: <strong style="color:${faultsResult.overall_risk_score >= 60 ? '#f87171' : '#4ade80'};">${faultsResult.overall_risk_score}/100</strong></p>
      <p>Faults detected: ${faultsResult.faults.length}</p>
    `;
    faultsResult.faults.forEach((f) => {
      html += `<p style="margin-left:16px;"><strong>[${f.severity.toUpperCase()}]</strong> ${f.description}</p>`;
    });
  }

  if (correctionResult) {
    html += `
      <h2 style="color:#93c5fd;font-size:18px;margin-top:24px;">Corrections</h2>
      <p>${correctionResult.summary}</p>
      <pre style="background:#1e293b;padding:16px;border-radius:8px;font-size:11px;color:#6ee7b7;white-space:pre-wrap;">${correctionResult.structured_text}</pre>
    `;
  }

  return html;
}
