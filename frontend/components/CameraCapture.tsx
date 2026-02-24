'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { Camera, CameraOff, RefreshCw } from 'lucide-react';

interface Props {
  onCapture: (file: File) => void;
}

export default function CameraCapture({ onCapture }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [active, setActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captured, setCaptured] = useState<string | null>(null);

  const startCamera = useCallback(async () => {
    setError(null);
    setCaptured(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setActive(true);
    } catch {
      setError('Camera not available or permission denied.');
    }
  }, []);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setActive(false);
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  const captureFrame = useCallback(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);

    const dataUrl = canvas.toDataURL('image/png');
    setCaptured(dataUrl);
    stopCamera();

    canvas.toBlob((blob) => {
      if (blob) {
        const file = new File([blob], `capture-${Date.now()}.png`, { type: 'image/png' });
        onCapture(file);
      }
    }, 'image/png');
  }, [onCapture, stopCamera]);

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Camera size={16} className="text-cyan-400" />
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-400">
          Camera Capture
        </h3>
      </div>

      {error && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-400">
          <CameraOff size={12} />
          {error}
        </div>
      )}

      {/* Preview */}
      <div className="relative overflow-hidden rounded-lg bg-gray-950">
        {captured ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={captured} alt="Captured" className="w-full rounded-lg" />
        ) : (
          <video
            ref={videoRef}
            className={`w-full rounded-lg ${active ? '' : 'hidden'}`}
            muted
            playsInline
          />
        )}
        {!active && !captured && (
          <div className="flex h-32 items-center justify-center">
            <Camera size={32} className="text-gray-700" />
          </div>
        )}
      </div>

      {/* Hidden canvas for capture */}
      <canvas ref={canvasRef} className="hidden" />

      <div className="mt-3 flex gap-2">
        {!active && !captured && (
          <button
            onClick={startCamera}
            className="flex items-center gap-2 rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white hover:bg-cyan-600"
          >
            <Camera size={14} />
            Start Camera
          </button>
        )}
        {active && (
          <button
            onClick={captureFrame}
            className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
          >
            <Camera size={14} />
            Capture
          </button>
        )}
        {captured && (
          <button
            onClick={() => { setCaptured(null); startCamera(); }}
            className="flex items-center gap-2 rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-400 hover:border-gray-600 hover:text-gray-200"
          >
            <RefreshCw size={14} />
            Retake
          </button>
        )}
      </div>
    </div>
  );
}
