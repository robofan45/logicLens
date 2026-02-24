'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, ShieldAlert, Shield, Info, ArrowUpDown } from 'lucide-react';
import type { FaultsResponse, Fault } from '@/lib/api';

const SEVERITY_CONFIG = {
  critical: { label: 'Critical', bg: 'bg-red-950/60', border: 'border-red-700', text: 'text-red-400', badge: 'bg-red-900 text-red-300', order: 0 },
  high:     { label: 'High',     bg: 'bg-orange-950/40', border: 'border-orange-800', text: 'text-orange-400', badge: 'bg-orange-900 text-orange-300', order: 1 },
  medium:   { label: 'Medium',   bg: 'bg-yellow-950/30', border: 'border-yellow-800', text: 'text-yellow-400', badge: 'bg-yellow-900 text-yellow-300', order: 2 },
  low:      { label: 'Low',      bg: 'bg-blue-950/30',   border: 'border-blue-800',   text: 'text-blue-400',   badge: 'bg-blue-900 text-blue-300',     order: 3 },
  info:     { label: 'Info',     bg: 'bg-gray-900',      border: 'border-gray-700',   text: 'text-gray-400',   badge: 'bg-gray-800 text-gray-300',     order: 4 },
};

function riskColor(score: number): string {
  if (score >= 80) return 'text-red-400';
  if (score >= 60) return 'text-orange-400';
  if (score >= 40) return 'text-yellow-400';
  return 'text-green-400';
}

function RiskBar({ score }: { score: number }) {
  const color =
    score >= 80 ? 'bg-red-500' : score >= 60 ? 'bg-orange-500' : score >= 40 ? 'bg-yellow-500' : 'bg-green-500';
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-gray-800">
      <motion.div
        className={`h-full rounded-full ${color}`}
        initial={{ width: 0 }}
        animate={{ width: `${score}%` }}
        transition={{ duration: 0.8, ease: 'easeOut' }}
      />
    </div>
  );
}

function FaultCard({ fault }: { fault: Fault }) {
  const cfg = SEVERITY_CONFIG[fault.severity] ?? SEVERITY_CONFIG.info;
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className={`rounded-lg border ${cfg.border} ${cfg.bg} p-4`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cfg.badge}`}>
          {cfg.label}
        </span>
        <span className="rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
          {fault.category}
        </span>
        {fault.standard_reference && (
          <span className="rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-500">
            {fault.standard_reference}
          </span>
        )}
      </div>

      <p className={`mt-2 text-sm font-medium ${cfg.text}`}>{fault.description}</p>

      {fault.affected_elements.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {fault.affected_elements.map((el) => (
            <span key={el} className="rounded bg-gray-800 px-1.5 py-0.5 font-mono text-xs text-gray-400">
              {el}
            </span>
          ))}
        </div>
      )}

      {fault.recommendation && (
        <p className="mt-2 text-xs text-gray-400">
          <span className="font-semibold text-gray-300">Recommendation: </span>
          {fault.recommendation}
        </p>
      )}
    </motion.div>
  );
}

interface Props {
  faultsData: FaultsResponse;
}

type SortKey = 'severity' | 'category';

export default function FaultDashboard({ faultsData }: Props) {
  const [sortBy, setSortBy] = useState<SortKey>('severity');

  const sorted = [...faultsData.faults].sort((a, b) => {
    if (sortBy === 'severity') {
      return (SEVERITY_CONFIG[a.severity]?.order ?? 5) - (SEVERITY_CONFIG[b.severity]?.order ?? 5);
    }
    return a.category.localeCompare(b.category);
  });

  const counts = Object.entries(SEVERITY_CONFIG).map(([key]) => ({
    key: key as Fault['severity'],
    count: faultsData.faults.filter((f) => f.severity === key).length,
  }));

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <AlertTriangle size={18} className="text-yellow-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          Fault Analysis
        </h2>
        <span className="ml-auto rounded-full bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
          {faultsData.faults.length} faults
        </span>
      </div>

      {/* Risk score */}
      <div className="mb-5 rounded-lg border border-gray-800 bg-gray-950 p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {faultsData.overall_risk_score >= 60 ? (
              <ShieldAlert size={16} className="text-red-400" />
            ) : (
              <Shield size={16} className="text-green-400" />
            )}
            <span className="text-sm text-gray-300">Overall Risk Score</span>
          </div>
          <span className={`text-2xl font-bold ${riskColor(faultsData.overall_risk_score)}`}>
            {faultsData.overall_risk_score}
            <span className="text-sm font-normal text-gray-600">/100</span>
          </span>
        </div>
        <RiskBar score={faultsData.overall_risk_score} />

        {/* Severity breakdown */}
        <div className="mt-3 flex flex-wrap gap-2">
          {counts.filter((c) => c.count > 0).map(({ key, count }) => {
            const cfg = SEVERITY_CONFIG[key];
            return (
              <span key={key} className={`rounded-full px-2 py-0.5 text-xs font-semibold ${cfg.badge}`}>
                {count} {cfg.label}
              </span>
            );
          })}
        </div>
      </div>

      {/* Standards checked */}
      {faultsData.standards_checked.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1">
          <span className="text-xs text-gray-600">Standards checked:</span>
          {faultsData.standards_checked.map((s) => (
            <span key={s} className="flex items-center gap-1 rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
              <Info size={10} /> {s}
            </span>
          ))}
        </div>
      )}

      {/* Sort control */}
      {faultsData.faults.length > 1 && (
        <div className="mb-3 flex items-center gap-2">
          <ArrowUpDown size={12} className="text-gray-600" />
          <span className="text-xs text-gray-600">Sort by:</span>
          {(['severity', 'category'] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortBy(k)}
              className={`rounded px-2 py-0.5 text-xs capitalize ${
                sortBy === k ? 'bg-blue-900 text-blue-300' : 'text-gray-500 hover:text-gray-300'
              }`}
            >
              {k}
            </button>
          ))}
        </div>
      )}

      {/* Fault list */}
      <div className="space-y-3">
        {sorted.length === 0 ? (
          <div className="rounded-lg border border-green-800 bg-green-950/20 p-4 text-center text-sm text-green-400">
            No faults detected 🎉
          </div>
        ) : (
          sorted.map((fault) => <FaultCard key={fault.fault_id} fault={fault} />)
        )}
      </div>
    </div>
  );
}
