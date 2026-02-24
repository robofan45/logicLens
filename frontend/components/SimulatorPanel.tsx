'use client';

import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Play, RotateCcw, Activity } from 'lucide-react';
import { simulateScan, toggleInput, resetSimulator } from '@/lib/api';
import type { SimulatorState } from '@/lib/api';

interface Props {
  sessionId: string;
}

export default function SimulatorPanel({ sessionId }: Props) {
  const [state, setState] = useState<SimulatorState | null>(null);
  const [scanTime, setScanTime] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runScan = useCallback(async () => {
    setIsRunning(true);
    setError(null);
    try {
      const res = await simulateScan(sessionId);
      setState(res.state);
      setScanTime(res.scan_time_ms);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Scan failed');
    } finally {
      setIsRunning(false);
    }
  }, [sessionId]);

  const handleToggle = useCallback(
    async (address: string, current: boolean) => {
      try {
        await toggleInput(sessionId, address, !current);
        await runScan();
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Toggle failed');
      }
    },
    [sessionId, runScan],
  );

  const handleReset = useCallback(async () => {
    try {
      await resetSimulator(sessionId);
      setState(null);
      setScanTime(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Reset failed');
    }
  }, [sessionId]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <Activity size={18} className="text-cyan-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          PLC Simulator
        </h2>
        {state && (
          <span className="ml-auto text-xs text-gray-500">
            Scan #{state.scan_count}
            {scanTime !== null && ` · ${scanTime.toFixed(1)} ms`}
          </span>
        )}
      </div>

      {/* Controls */}
      <div className="mb-5 flex gap-3">
        <button
          onClick={runScan}
          disabled={isRunning}
          className="flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-600 disabled:opacity-50"
        >
          <Play size={14} />
          {isRunning ? 'Scanning…' : 'Run Scan'}
        </button>
        <button
          onClick={handleReset}
          className="flex items-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-400 hover:border-gray-600 hover:text-gray-200"
        >
          <RotateCcw size={14} />
          Reset
        </button>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {!state ? (
        <p className="text-center text-sm text-gray-600">
          Click &ldquo;Run Scan&rdquo; to start the simulation.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Inputs */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">
              Inputs ({Object.keys(state.inputs).length})
            </h3>
            <div className="space-y-1.5">
              {Object.entries(state.inputs).map(([addr, val]) => (
                <motion.button
                  key={addr}
                  onClick={() => handleToggle(addr, val)}
                  whileTap={{ scale: 0.97 }}
                  className="flex w-full items-center justify-between rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm transition-colors hover:border-gray-700"
                >
                  <span className="font-mono text-gray-300">{addr}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-bold ${
                      val
                        ? 'bg-green-900 text-green-300'
                        : 'bg-gray-800 text-gray-500'
                    }`}
                  >
                    {val ? 'ON' : 'OFF'}
                  </span>
                </motion.button>
              ))}
            </div>
          </div>

          {/* Outputs */}
          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">
              Outputs ({Object.keys(state.outputs).length})
            </h3>
            <div className="space-y-1.5">
              {Object.entries(state.outputs).map(([addr, val]) => (
                <div
                  key={addr}
                  className="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm"
                >
                  <span className="font-mono text-gray-300">{addr}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-bold ${
                      val
                        ? 'bg-orange-900 text-orange-300'
                        : 'bg-gray-800 text-gray-500'
                    }`}
                  >
                    {val ? 'ON' : 'OFF'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Timers */}
          {Object.keys(state.timers).length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">
                Timers
              </h3>
              <div className="space-y-1.5">
                {Object.entries(state.timers).map(([addr, t]) => (
                  <div
                    key={addr}
                    className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2"
                  >
                    <span className="font-mono text-xs text-gray-300">{addr}</span>
                    <pre className="mt-1 text-xs text-gray-500">
                      {JSON.stringify(t, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Counters */}
          {Object.keys(state.counters).length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-gray-500">
                Counters
              </h3>
              <div className="space-y-1.5">
                {Object.entries(state.counters).map(([addr, c]) => (
                  <div
                    key={addr}
                    className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2"
                  >
                    <span className="font-mono text-xs text-gray-300">{addr}</span>
                    <pre className="mt-1 text-xs text-gray-500">
                      {JSON.stringify(c, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
