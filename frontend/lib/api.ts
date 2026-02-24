import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface BoundingBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  confidence: number;
  class_name: string;
  class_id: number;
}

export interface ParsedElement {
  id: string;
  element_type: string;
  address: string;
  label: string;
  rung: number;
  position_x: number;
  position_y: number;
  bounding_box?: BoundingBox;
  properties: Record<string, unknown>;
  confidence: number;
}

export interface ParseResponse {
  session_id: string;
  parsed_elements: ParsedElement[];
  yolo_detections: BoundingBox[];
  total_rungs: number;
  uncertainties: string[];
  image_width: number;
  image_height: number;
  blur_score: number;
  processing_time_ms: number;
}

export interface SignalPath {
  rung: number;
  path_elements: string[];
  is_energized: boolean;
  conditions: string[];
}

export interface TraceResponse {
  session_id: string;
  execution_order: string[];
  signal_paths: SignalPath[];
  dependency_map: Record<string, string[]>;
  uncertainties: string[];
  processing_time_ms: number;
}

export interface Fault {
  fault_id: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  category: string;
  description: string;
  affected_elements: string[];
  recommendation: string;
  standard_reference: string;
}

export interface FaultsResponse {
  session_id: string;
  faults: Fault[];
  overall_risk_score: number;
  standards_checked: string[];
  processing_time_ms: number;
}

export interface CorrectionResponse {
  session_id: string;
  corrected_rungs: Array<{
    rung_number: number;
    original_description: string;
    corrected_description: string;
    changes_made: string[];
  }>;
  summary: string;
  structured_text: string;
  uncertainties: string[];
  processing_time_ms: number;
}

export interface SimulatorState {
  inputs: Record<string, boolean>;
  outputs: Record<string, boolean>;
  timers: Record<string, Record<string, unknown>>;
  counters: Record<string, Record<string, unknown>>;
  scan_count: number;
}

export interface ScanResponse {
  session_id: string;
  state: SimulatorState;
  rung_results: Array<Record<string, unknown>>;
  scan_time_ms: number;
}

export async function parseImage(
  file: File,
  platform?: string,
  sessionId?: string,
): Promise<ParseResponse> {
  const formData = new FormData();
  formData.append('file', file);
  if (platform) formData.append('plc_platform', platform);
  if (sessionId) formData.append('session_id', sessionId);
  const res = await axios.post(`${API_BASE}/api/analyze/parse`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

export async function traceSignals(sessionId: string): Promise<TraceResponse> {
  const res = await axios.post(`${API_BASE}/api/analyze/trace`, { session_id: sessionId });
  return res.data;
}

export async function analyzeFaults(
  sessionId: string,
  userContext?: string,
): Promise<FaultsResponse> {
  const res = await axios.post(`${API_BASE}/api/analyze/faults`, {
    session_id: sessionId,
    user_context: userContext || '',
  });
  return res.data;
}

export async function generateCorrection(
  sessionId: string,
  instructions?: string,
): Promise<CorrectionResponse> {
  const res = await axios.post(`${API_BASE}/api/generate/correction`, {
    session_id: sessionId,
    user_instructions: instructions || '',
  });
  return res.data;
}

export async function generateTranslation(
  sessionId: string,
  source: string,
  target: string,
) {
  const res = await axios.post(`${API_BASE}/api/generate/translation`, {
    session_id: sessionId,
    source_platform: source,
    target_platform: target,
  });
  return res.data;
}

export async function structureLadder(sessionId: string) {
  const res = await axios.post(`${API_BASE}/api/analyze/structure`, { session_id: sessionId });
  return res.data;
}

export async function simulateScan(
  sessionId: string,
  scanCount?: number,
): Promise<ScanResponse> {
  const res = await axios.post(`${API_BASE}/api/simulate/scan`, {
    session_id: sessionId,
    scan_count: scanCount || 1,
  });
  return res.data;
}

export async function toggleInput(
  sessionId: string,
  address: string,
  value?: boolean,
) {
  const res = await axios.post(`${API_BASE}/api/simulate/toggle`, {
    session_id: sessionId,
    address,
    value,
  });
  return res.data;
}

export async function resetSimulator(sessionId: string) {
  const res = await axios.post(`${API_BASE}/api/simulate/reset`, { session_id: sessionId });
  return res.data;
}

export async function exportJson(sessionId: string) {
  const res = await axios.post(`${API_BASE}/api/export/json`, { session_id: sessionId });
  return res.data;
}

export async function exportST(sessionId: string) {
  const res = await axios.post(`${API_BASE}/api/export/st`, { session_id: sessionId });
  return res.data;
}

export async function healthCheck() {
  const res = await axios.get(`${API_BASE}/health`);
  return res.data;
}
