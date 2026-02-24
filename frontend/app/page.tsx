'use client';

import { useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, AlertCircle, X } from 'lucide-react';

import ImageUploader from '@/components/ImageUploader';
import PipelineStepper from '@/components/PipelineStepper';
import BoundingBoxCanvas from '@/components/BoundingBoxCanvas';
import SignalFlowView from '@/components/SignalFlowView';
import FaultDashboard from '@/components/FaultDashboard';
import CorrectionView from '@/components/CorrectionView';
import SimulatorPanel from '@/components/SimulatorPanel';
import LadderDiagramView from '@/components/LadderDiagramView';
import ExportPanel from '@/components/ExportPanel';
import ReportGenerator from '@/components/ReportGenerator';
import HistorySidebar, { addSessionToHistory } from '@/components/HistorySidebar';

import {
  parseImage,
  traceSignals,
  analyzeFaults,
  generateCorrection,
} from '@/lib/api';
import type { ParseResponse, TraceResponse, FaultsResponse, CorrectionResponse } from '@/lib/api';

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentStage, setCurrentStage] = useState(0);
  const [completedStages, setCompletedStages] = useState<number[]>([]);

  const [parseResult, setParseResult] = useState<ParseResponse | null>(null);
  const [traceResult, setTraceResult] = useState<TraceResponse | null>(null);
  const [faultsResult, setFaultsResult] = useState<FaultsResponse | null>(null);
  const [correctionResult, setCorrectionResult] = useState<CorrectionResponse | null>(null);
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showSidebar, setShowSidebar] = useState(false);

  const resetResults = useCallback(() => {
    setParseResult(null);
    setTraceResult(null);
    setFaultsResult(null);
    setCorrectionResult(null);
    setUploadedImage(null);
    setCompletedStages([]);
    setCurrentStage(0);
    setSessionId(null);
    setError(null);
  }, []);

  const handleUpload = useCallback(async (file: File, platform: string) => {
    resetResults();
    setIsLoading(true);
    setError(null);
    setCurrentStage(1);

    try {
      const imageUrl = URL.createObjectURL(file);
      setUploadedImage(imageUrl);

      // Stage 1 – parse
      const parsed = await parseImage(file, platform);
      setParseResult(parsed);
      setSessionId(parsed.session_id);
      setCompletedStages([1]);
      setCurrentStage(2);

      // Stage 2 – trace
      const traced = await traceSignals(parsed.session_id);
      setTraceResult(traced);
      setCompletedStages([1, 2]);
      setCurrentStage(3);

      // Stage 3 – faults
      const faulted = await analyzeFaults(parsed.session_id);
      setFaultsResult(faulted);
      setCompletedStages([1, 2, 3]);
      setCurrentStage(4);

      // Stage 4 – correction
      const corrected = await generateCorrection(parsed.session_id);
      setCorrectionResult(corrected);
      setCompletedStages([1, 2, 3, 4]);

      // Persist to history
      await addSessionToHistory({
        sessionId: parsed.session_id,
        timestamp: Date.now(),
        thumbnail: imageUrl,
        summary: `${parsed.parsed_elements.length} elements, ${faulted.faults.length} faults`,
      });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Analysis failed. Is the backend running?';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [resetResults]);

  const handleSelectSession = useCallback((sid: string) => {
    setSessionId(sid);
    setShowSidebar(false);
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-gray-800 bg-gray-950/90 px-6 py-3 backdrop-blur">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600">
              <span className="text-sm font-bold text-white">LL</span>
            </div>
            <h1 className="text-lg font-bold tracking-tight">LogicLens</h1>
            <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-500">Beta</span>
          </div>

          <div className="flex items-center gap-2">
            {sessionId && (
              <span className="hidden font-mono text-xs text-gray-600 sm:block">
                {sessionId.slice(0, 8)}…
              </span>
            )}
            <ExportPanel sessionId={sessionId} />
            <button
              onClick={() => setShowSidebar((v) => !v)}
              title="Session history"
              className={`rounded-lg p-2 transition-colors ${
                showSidebar ? 'bg-blue-900 text-blue-300' : 'text-gray-500 hover:bg-gray-800 hover:text-gray-300'
              }`}
            >
              <History size={16} />
            </button>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* ── Sidebar ────────────────────────────────────────── */}
        <AnimatePresence>
          {showSidebar && (
            <motion.div
              initial={{ x: -288, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -288, opacity: 0 }}
              transition={{ type: 'tween', duration: 0.2 }}
              className="fixed left-0 top-[57px] z-20 h-[calc(100vh-57px)]"
            >
              <HistorySidebar
                onSelectSession={handleSelectSession}
                currentSessionId={sessionId}
              />
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Main content ───────────────────────────────────── */}
        <main className="w-full max-w-7xl mx-auto p-4 sm:p-6 space-y-6">
          {/* Pipeline stepper */}
          <PipelineStepper currentStage={currentStage} completedStages={completedStages} />

          {/* Global error banner */}
          <AnimatePresence>
            {error && (
              <motion.div
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                className="flex items-start gap-3 rounded-xl border border-red-700 bg-red-950/50 p-4 text-sm text-red-300"
              >
                <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-400" />
                <span className="flex-1">{error}</span>
                <button onClick={() => setError(null)}>
                  <X size={14} className="text-red-500 hover:text-red-300" />
                </button>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Upload */}
          <ImageUploader onUpload={handleUpload} isLoading={isLoading} />

          {/* Stage 1 results */}
          <AnimatePresence>
            {parseResult && uploadedImage && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                className="grid grid-cols-1 gap-6 lg:grid-cols-2"
              >
                <BoundingBoxCanvas
                  imageUrl={uploadedImage}
                  detections={parseResult.yolo_detections}
                  imageWidth={parseResult.image_width}
                  imageHeight={parseResult.image_height}
                />
                <LadderDiagramView
                  elements={parseResult.parsed_elements}
                  totalRungs={parseResult.total_rungs}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Stage 2 results */}
          <AnimatePresence>
            {traceResult && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <SignalFlowView traceData={traceResult} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Stage 3 results */}
          <AnimatePresence>
            {faultsResult && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <FaultDashboard faultsData={faultsResult} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Stage 4 results */}
          <AnimatePresence>
            {correctionResult && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <CorrectionView correctionData={correctionResult} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Simulator – available once stage 1 complete */}
          <AnimatePresence>
            {sessionId && completedStages.includes(1) && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <SimulatorPanel sessionId={sessionId} />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Report generator – available once all stages complete */}
          <AnimatePresence>
            {completedStages.length === 4 && (
              <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
                <ReportGenerator
                  parseResult={parseResult}
                  traceResult={traceResult}
                  faultsResult={faultsResult}
                  correctionResult={correctionResult}
                  uploadedImage={uploadedImage}
                />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Footer spacer */}
          <div className="h-12" />
        </main>
      </div>
    </div>
  );
}
