'use client';

import { useState, useCallback } from 'react';
import { Download, FileJson, FileCode, FileText } from 'lucide-react';
import { exportJson, exportST } from '@/lib/api';

interface Props {
  sessionId: string | null;
}

export default function ExportPanel({ sessionId }: Props) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExportJson = useCallback(async () => {
    if (!sessionId) return;
    setLoading('json');
    setError(null);
    try {
      const data = await exportJson(sessionId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      downloadBlob(blob, `logiclens-${sessionId.slice(0, 8)}.json`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed');
    } finally {
      setLoading(null);
    }
  }, [sessionId]);

  const handleExportST = useCallback(async () => {
    if (!sessionId) return;
    setLoading('st');
    setError(null);
    try {
      const data = await exportST(sessionId);
      const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
      const blob = new Blob([content], { type: 'text/plain' });
      downloadBlob(blob, `logiclens-${sessionId.slice(0, 8)}.st`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Export failed');
    } finally {
      setLoading(null);
    }
  }, [sessionId]);

  const handleExportPdf = useCallback(async () => {
    if (!sessionId) return;
    setLoading('pdf');
    setError(null);
    try {
      const [html2canvas, { jsPDF }] = await Promise.all([
        import('html2canvas').then((m) => m.default),
        import('jspdf'),
      ]);
      const canvas = await html2canvas(document.body, { useCORS: true, scale: 1 });
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF({ orientation: 'landscape', unit: 'px', format: [canvas.width, canvas.height] });
      pdf.addImage(imgData, 'PNG', 0, 0, canvas.width, canvas.height);
      pdf.save(`logiclens-${sessionId.slice(0, 8)}.pdf`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'PDF export failed');
    } finally {
      setLoading(null);
    }
  }, [sessionId]);

  if (!sessionId) return null;

  return (
    <div className="flex items-center gap-2">
      {error && (
        <span className="text-xs text-red-400">{error}</span>
      )}
      <button
        onClick={handleExportJson}
        disabled={!!loading}
        title="Export JSON"
        className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:border-gray-600 hover:text-gray-200 disabled:opacity-50"
      >
        <FileJson size={13} />
        {loading === 'json' ? '…' : 'JSON'}
      </button>
      <button
        onClick={handleExportST}
        disabled={!!loading}
        title="Export Structured Text"
        className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:border-gray-600 hover:text-gray-200 disabled:opacity-50"
      >
        <FileCode size={13} />
        {loading === 'st' ? '…' : 'ST Code'}
      </button>
      <button
        onClick={handleExportPdf}
        disabled={!!loading}
        title="Export PDF"
        className="flex items-center gap-1.5 rounded-lg border border-gray-700 px-3 py-1.5 text-xs text-gray-400 hover:border-gray-600 hover:text-gray-200 disabled:opacity-50"
      >
        <FileText size={13} />
        {loading === 'pdf' ? '…' : 'PDF'}
      </button>
      <Download size={13} className="text-gray-600" />
    </div>
  );
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
