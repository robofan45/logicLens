'use client';

import { useState, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, X, Image as ImageIcon, AlertCircle, Cpu } from 'lucide-react';

const PLATFORMS = [
  { value: 'allen_bradley', label: 'Allen-Bradley / Rockwell' },
  { value: 'siemens', label: 'Siemens' },
  { value: 'mitsubishi', label: 'Mitsubishi' },
  { value: 'omron', label: 'Omron' },
  { value: 'schneider', label: 'Schneider Electric' },
  { value: 'generic', label: 'Generic / Unknown' },
];

const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5 MB
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/jpg', 'image/webp'];

interface Props {
  onUpload: (file: File, platform: string) => void;
  isLoading: boolean;
}

export default function ImageUploader({ onUpload, isLoading }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [platform, setPlatform] = useState('generic');
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validateAndSet = useCallback((f: File) => {
    setError(null);
    if (!ACCEPTED_TYPES.includes(f.type)) {
      setError('Invalid file type. Please upload a PNG, JPG, or WebP image.');
      return;
    }
    if (f.size > MAX_FILE_SIZE) {
      setError(`File too large. Maximum size is ${MAX_FILE_SIZE / (1024 * 1024)} MB.`);
      return;
    }
    setFile(f);
    setPreview(URL.createObjectURL(f));
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) validateAndSet(dropped);
    },
    [validateAndSet],
  );

  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) validateAndSet(selected);
    },
    [validateAndSet],
  );

  const clearFile = useCallback(() => {
    setFile(null);
    setPreview(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = '';
  }, []);

  const handleAnalyze = useCallback(() => {
    if (file) onUpload(file, platform);
  }, [file, platform, onUpload]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-6">
      <div className="mb-4 flex items-center gap-2">
        <Cpu size={18} className="text-blue-400" />
        <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">
          Upload Ladder Logic Image
        </h2>
      </div>

      {/* Platform selector */}
      <div className="mb-4">
        <label className="mb-1 block text-xs text-gray-500">PLC Platform</label>
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          disabled={isLoading}
          className="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 focus:border-blue-500 focus:outline-none disabled:opacity-50"
        >
          {PLATFORMS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      </div>

      {/* Drop zone */}
      <AnimatePresence mode="wait">
        {!preview ? (
          <motion.div
            key="dropzone"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            className={`flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 transition-colors ${
              dragOver
                ? 'border-blue-500 bg-blue-950/30'
                : 'border-gray-700 hover:border-gray-600 hover:bg-gray-800/50'
            }`}
          >
            <Upload
              size={32}
              className={dragOver ? 'text-blue-400' : 'text-gray-600'}
            />
            <div className="text-center">
              <p className="text-sm text-gray-400">
                Drag & drop or{' '}
                <span className="text-blue-400 underline">browse</span>
              </p>
              <p className="mt-1 text-xs text-gray-600">PNG, JPG, WebP · max 5 MB</p>
            </div>
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/jpg,image/webp"
              className="hidden"
              onChange={handleFileChange}
            />
          </motion.div>
        ) : (
          <motion.div
            key="preview"
            initial={{ opacity: 0, scale: 0.97 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="relative overflow-hidden rounded-xl border border-gray-700 bg-gray-800"
          >
            <button
              onClick={clearFile}
              disabled={isLoading}
              className="absolute right-2 top-2 z-10 rounded-full bg-gray-900/80 p-1 text-gray-400 hover:text-red-400 disabled:opacity-50"
              aria-label="Remove image"
            >
              <X size={14} />
            </button>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={preview}
              alt="Preview"
              className="max-h-64 w-full object-contain"
            />
            <div className="flex items-center gap-2 border-t border-gray-700 px-4 py-2">
              <ImageIcon size={14} className="text-gray-500" />
              <span className="truncate text-xs text-gray-400">{file?.name}</span>
              <span className="ml-auto text-xs text-gray-600">
                {file ? (file.size / 1024).toFixed(0) : 0} KB
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-3 flex items-center gap-2 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-400"
          >
            <AlertCircle size={14} />
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Analyze button */}
      <button
        onClick={handleAnalyze}
        disabled={!file || isLoading}
        className="mt-4 w-full rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {isLoading ? (
          <span className="flex items-center justify-center gap-2">
            <svg
              className="h-4 w-4 animate-spin"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8z"
              />
            </svg>
            Analyzing…
          </span>
        ) : (
          'Analyze Ladder Logic'
        )}
      </button>
    </div>
  );
}
