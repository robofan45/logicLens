'use client';

import { motion } from 'framer-motion';
import { Scan, GitBranch, AlertTriangle, Wrench, Check } from 'lucide-react';

const STAGES = [
  { id: 1, label: 'Element Recognition', icon: Scan },
  { id: 2, label: 'Signal Flow Trace', icon: GitBranch },
  { id: 3, label: 'Fault Analysis', icon: AlertTriangle },
  { id: 4, label: 'Correction & Translation', icon: Wrench },
];

interface Props {
  currentStage: number;
  completedStages: number[];
}

export default function PipelineStepper({ currentStage, completedStages }: Props) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 px-6 py-5">
      <div className="flex items-center justify-between">
        {STAGES.map((stage, idx) => {
          const Icon = stage.icon;
          const isCompleted = completedStages.includes(stage.id);
          const isActive = currentStage === stage.id;
          const isPending = !isCompleted && !isActive;

          return (
            <div key={stage.id} className="flex flex-1 items-center">
              {/* Step circle */}
              <div className="flex flex-col items-center">
                <motion.div
                  animate={{
                    backgroundColor: isCompleted
                      ? '#16a34a'
                      : isActive
                        ? '#2563eb'
                        : '#1f2937',
                    borderColor: isCompleted
                      ? '#16a34a'
                      : isActive
                        ? '#2563eb'
                        : '#374151',
                  }}
                  transition={{ duration: 0.3 }}
                  className="flex h-10 w-10 items-center justify-center rounded-full border-2"
                >
                  {isCompleted ? (
                    <Check size={16} className="text-white" />
                  ) : (
                    <Icon
                      size={16}
                      className={
                        isActive
                          ? 'text-white'
                          : isPending
                            ? 'text-gray-600'
                            : 'text-white'
                      }
                    />
                  )}
                </motion.div>

                {/* Stage label */}
                <span
                  className={`mt-2 hidden text-center text-xs sm:block ${
                    isCompleted
                      ? 'text-green-400'
                      : isActive
                        ? 'font-semibold text-blue-400'
                        : 'text-gray-600'
                  }`}
                >
                  {stage.label}
                </span>
              </div>

              {/* Connector line */}
              {idx < STAGES.length - 1 && (
                <div className="relative mx-2 h-0.5 flex-1 overflow-hidden rounded-full bg-gray-800">
                  <motion.div
                    className="absolute inset-y-0 left-0 bg-green-500"
                    initial={{ width: '0%' }}
                    animate={{
                      width: completedStages.includes(stage.id) ? '100%' : '0%',
                    }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
