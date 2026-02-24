'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { GitBranch, ChevronDown, ChevronRight, Zap, ZapOff } from 'lucide-react';
import type { TraceResponse } from '@/lib/api';

interface Props {
  traceData: TraceResponse;
}

export default function SignalFlowView({ traceData }: Props) {
  const [expandedRungs, setExpandedRungs] = useState<Set<number>>(new Set());
  const [showDeps, setShowDeps] = useState(false);

  const toggleRung = (rung: number) => {
    setExpandedRungs((prev) => {
      const next = new Set(prev);
      next.has(rung) ? next.delete(rung) : next.add(rung);
      return next;
    });
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <GitBranch size={18} className="text-purple-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          Signal Flow Trace
        </h2>
        <span className="ml-auto rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
          {traceData.signal_paths.length} rungs
        </span>
      </div>

      {/* Execution order */}
      {traceData.execution_order.length > 0 && (
        <div className="mb-4 rounded-lg border border-gray-800 bg-gray-950 p-3">
          <p className="mb-2 text-xs font-semibold text-gray-500">Execution Order</p>
          <div className="flex flex-wrap gap-1">
            {traceData.execution_order.map((id, i) => (
              <span key={i} className="rounded bg-gray-800 px-2 py-0.5 font-mono text-xs text-gray-300">
                {i + 1}. {id}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Signal paths */}
      <div className="space-y-2">
        {traceData.signal_paths.map((sp) => (
          <motion.div
            key={sp.rung}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            className={`rounded-lg border ${
              sp.is_energized ? 'border-green-800 bg-green-950/30' : 'border-gray-800 bg-gray-950'
            }`}
          >
            <button
              className="flex w-full items-center gap-3 px-4 py-3 text-left"
              onClick={() => toggleRung(sp.rung)}
            >
              {sp.is_energized ? (
                <Zap size={14} className="shrink-0 text-green-400" />
              ) : (
                <ZapOff size={14} className="shrink-0 text-gray-600" />
              )}
              <span className="text-sm font-medium text-gray-300">
                Rung {sp.rung}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-xs ${
                  sp.is_energized
                    ? 'bg-green-900 text-green-300'
                    : 'bg-gray-800 text-gray-500'
                }`}
              >
                {sp.is_energized ? 'Energized' : 'De-energized'}
              </span>
              <span className="ml-auto text-gray-600">
                {expandedRungs.has(sp.rung) ? (
                  <ChevronDown size={14} />
                ) : (
                  <ChevronRight size={14} />
                )}
              </span>
            </button>

            {expandedRungs.has(sp.rung) && (
              <div className="border-t border-gray-800 px-4 pb-3 pt-2">
                {sp.path_elements.length > 0 && (
                  <div className="mb-2">
                    <p className="mb-1 text-xs text-gray-600">Path Elements</p>
                    <div className="flex flex-wrap gap-1">
                      {sp.path_elements.map((el, i) => (
                        <span
                          key={i}
                          className="rounded bg-gray-800 px-2 py-0.5 font-mono text-xs text-gray-300"
                        >
                          {el}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {sp.conditions.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs text-gray-600">Conditions</p>
                    <ul className="space-y-0.5">
                      {sp.conditions.map((cond, i) => (
                        <li key={i} className="text-xs text-gray-400">
                          • {cond}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </motion.div>
        ))}
      </div>

      {/* Dependency map */}
      {Object.keys(traceData.dependency_map).length > 0 && (
        <div className="mt-4">
          <button
            className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-300"
            onClick={() => setShowDeps(!showDeps)}
          >
            {showDeps ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            Dependency Map ({Object.keys(traceData.dependency_map).length} elements)
          </button>
          {showDeps && (
            <div className="mt-2 rounded-lg border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400">
              {Object.entries(traceData.dependency_map).map(([key, deps]) => (
                <div key={key} className="mb-1">
                  <span className="text-blue-400">{key}</span>
                  {' → '}
                  {deps.length > 0 ? deps.join(', ') : <span className="text-gray-600">none</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {traceData.uncertainties.length > 0 && (
        <div className="mt-4 rounded-lg border border-yellow-800 bg-yellow-950/20 p-3">
          <p className="mb-1 text-xs font-semibold text-yellow-400">Uncertainties</p>
          {traceData.uncertainties.map((u, i) => (
            <p key={i} className="text-xs text-yellow-600">
              • {u}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
