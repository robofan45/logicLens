'use client';

import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Wrench, Copy, Check, ChevronDown, ChevronRight } from 'lucide-react';
import type { CorrectionResponse } from '@/lib/api';

interface Props {
  correctionData: CorrectionResponse;
}

export default function CorrectionView({ correctionData }: Props) {
  const [copied, setCopied] = useState(false);
  const [expandedRungs, setExpandedRungs] = useState<Set<number>>(new Set([0]));

  const copyToClipboard = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(correctionData.structured_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback: no-op
    }
  }, [correctionData.structured_text]);

  const toggleRung = (idx: number) => {
    setExpandedRungs((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <Wrench size={18} className="text-emerald-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          Correction & Translation
        </h2>
      </div>

      {/* Summary */}
      {correctionData.summary && (
        <div className="mb-5 rounded-lg border border-gray-700 bg-gray-800 p-4">
          <p className="text-sm text-gray-300">{correctionData.summary}</p>
        </div>
      )}

      {/* Corrected rungs */}
      {correctionData.corrected_rungs.length > 0 && (
        <div className="mb-6 space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
            Corrected Rungs ({correctionData.corrected_rungs.length})
          </h3>
          {correctionData.corrected_rungs.map((rung, idx) => (
            <div key={idx} className="rounded-lg border border-gray-800 bg-gray-950">
              <button
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                onClick={() => toggleRung(idx)}
              >
                <span className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-xs text-gray-400">
                  Rung {rung.rung_number}
                </span>
                {rung.changes_made.length > 0 && (
                  <span className="rounded-full bg-emerald-900 px-2 py-0.5 text-xs text-emerald-300">
                    {rung.changes_made.length} change{rung.changes_made.length !== 1 ? 's' : ''}
                  </span>
                )}
                <span className="ml-auto text-gray-600">
                  {expandedRungs.has(idx) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
              </button>

              {expandedRungs.has(idx) && (
                <div className="border-t border-gray-800 px-4 pb-4 pt-3 space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <p className="mb-1 text-xs text-gray-600">Original</p>
                      <p className="rounded bg-gray-900 p-2 text-xs text-gray-400">
                        {rung.original_description || <span className="italic text-gray-600">—</span>}
                      </p>
                    </div>
                    <div>
                      <p className="mb-1 text-xs text-gray-600">Corrected</p>
                      <p className="rounded bg-gray-900 p-2 text-xs text-emerald-300">
                        {rung.corrected_description || <span className="italic text-gray-600">—</span>}
                      </p>
                    </div>
                  </div>
                  {rung.changes_made.length > 0 && (
                    <ul className="space-y-0.5">
                      {rung.changes_made.map((change, ci) => (
                        <li key={ci} className="text-xs text-gray-500">
                          • {change}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Structured Text code */}
      {correctionData.structured_text && (
        <div>
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500">
              Structured Text (IEC 61131-3)
            </h3>
            <button
              onClick={copyToClipboard}
              className="flex items-center gap-1.5 rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-400 transition-colors hover:border-gray-600 hover:text-gray-200"
            >
              {copied ? (
                <>
                  <Check size={12} className="text-green-400" />
                  Copied!
                </>
              ) : (
                <>
                  <Copy size={12} />
                  Copy
                </>
              )}
            </button>
          </div>
          <motion.pre
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="max-h-96 overflow-auto rounded-xl border border-gray-800 bg-gray-950 p-4 font-mono text-xs leading-relaxed text-green-300"
          >
            {correctionData.structured_text}
          </motion.pre>
        </div>
      )}

      {/* Uncertainties */}
      {correctionData.uncertainties.length > 0 && (
        <div className="mt-4 rounded-lg border border-yellow-800 bg-yellow-950/20 p-3">
          <p className="mb-1 text-xs font-semibold text-yellow-400">Uncertainties</p>
          {correctionData.uncertainties.map((u, i) => (
            <p key={i} className="text-xs text-yellow-600">• {u}</p>
          ))}
        </div>
      )}
    </div>
  );
}
