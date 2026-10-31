// PLC platforms, keyed by the contract enum (contract/program.schema.json "platform").

export type PlatformId =
  | "rockwell_logix"
  | "rockwell_slc"
  | "siemens_tia"
  | "schneider"
  | "mitsubishi"
  | "omron"
  | "abb"
  | "generic_iec"
  | "unknown";

export interface PlatformInfo {
  id: PlatformId;
  label: string;
  addressing: string;
}

export const PLATFORMS: PlatformInfo[] = [
  { id: "unknown", label: "Auto-detect", addressing: "guessed from the addresses" },
  { id: "rockwell_logix", label: "Rockwell Studio 5000 (Logix)", addressing: "Start_PB, Local:1:I.Data.0" },
  { id: "rockwell_slc", label: "Rockwell RSLogix 500 (SLC / MicroLogix)", addressing: "I:1/0, O:2/0, B3:0/1, T4:0" },
  { id: "siemens_tia", label: "Siemens TIA Portal / STEP 7", addressing: "%I0.0, %Q0.0, %M10.0" },
  { id: "schneider", label: "Schneider EcoStruxure / Unity", addressing: "%I0.0.0, %Q0.0.0, %MW0" },
  { id: "mitsubishi", label: "Mitsubishi GX Works", addressing: "X0, Y0, M0, T0" },
  { id: "omron", label: "Omron Sysmac / CX-Programmer", addressing: "0.00, 100.00, W0.00" },
  { id: "abb", label: "ABB AC500", addressing: "%IX0.0, %QX0.0" },
  { id: "generic_iec", label: "Generic IEC 61131-3", addressing: "START_PB, MOTOR_RUN" },
];

const IDS = new Set<string>(PLATFORMS.map((p) => p.id));

export function isPlatformId(x: unknown): x is PlatformId {
  return typeof x === "string" && IDS.has(x);
}

export function platformLabel(id: string | null | undefined): string {
  return PLATFORMS.find((p) => p.id === id)?.label ?? "Auto-detect";
}
