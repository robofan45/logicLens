// Built-in example programs in LogicLens Ladder Text (contract/README.md §1).
// Each one is real, parseable logic; the analyzer runs on it exactly as on user input.

import type { PlatformId } from "./platforms";

export interface Sample {
  id: string;
  name: string;
  summary: string;
  platform: PlatformId;
  text: string;
}

export const SAMPLES: Sample[] = [
  {
    id: "faulty-demo",
    name: "Demo: motor + alarm logic with faults",
    summary: "The old mock-up program written as real ladder, plus common field mistakes. Good first run.",
    platform: "generic_iec",
    text: `// Motor start/stop with seal-in
[XIC(START_PB),XIC(MOTOR_OUT)]XIO(STOP_PB)OTE(MOTOR_OUT);
// Overload delay timer (preset unreadable on the printout)
XIC(MOTOR_OUT)XIC(OVL_FAULT)TON(DELAY_TMR,?,0);
// Alarm after the delay, unless E-stop is pressed
XIO(E_STOP)XIC(DELAY_TMR.DN)OTE(ALARM_OUT);
// Reset the delay timer
XIC(RESET_PB)RES(DELAY_TMR);
// Remote start added later by another engineer
XIC(REMOTE_START)OTE(MOTOR_OUT);
// Horn latches on alarm
XIC(ALARM_OUT)OTL(HORN);
// Production counter
XIC(PART_SENSOR)CTU(PART_COUNT,100,0);
// Auto lamp
XIC(AUTO_MODE)XIO(AUTO_MODE)OTE(AUTO_LAMP);`,
  },
  {
    id: "motor",
    name: "Motor starter (fail-safe wiring)",
    summary: "Stop and overload wired NC and examined with XIC; latched overload alarm with acknowledge.",
    platform: "rockwell_logix",
    text: `// Motor M-101: Stop_PB and OL_Relay are wired NC (fail-safe), so they read 1 when healthy
XIC(Stop_PB)XIC(OL_Relay)[XIC(Start_PB),XIC(Motor_Run)]OTE(Motor_Run);
// Run lamp
XIC(Motor_Run)OTE(Run_Lamp);
// Overload alarm latches until acknowledged
XIO(OL_Relay)OTL(OL_Alarm);
// Acknowledge only once the overload has cleared
XIC(Ack_PB)XIC(OL_Relay)OTU(OL_Alarm);`,
  },
  {
    id: "conveyor",
    name: "Conveyor with start warning and jam detection",
    summary: "Start-delay horn, jam timer with latch and reset, carton counter with one-shot.",
    platform: "rockwell_logix",
    text: `// Conveyor CV-3: run permissive (guards closed, no jam) starts a 3 s warning delay
XIC(Guard_Closed)XIO(Jam_Detected)XIC(Run_Cmd)TON(Start_Delay,3000,0);
// Horn sounds while the delay is timing
XIC(Start_Delay.TT)OTE(Warning_Horn);
// Motor runs after the delay
XIC(Start_Delay.DN)OTE(Conveyor_Motor);
// Jam: photo-eye blocked for 5 s while running
XIC(Conveyor_Motor)XIC(PE_Blocked)TON(Jam_Timer,5000,0);
XIC(Jam_Timer.DN)OTL(Jam_Detected);
// Jam reset needs the photo-eye clear
XIC(Jam_Reset_PB)XIO(PE_Blocked)OTU(Jam_Detected);
// Count cartons on the leading edge
XIC(PE_Blocked)ONS(PE_OS)CTU(Carton_Count,500,0);
XIC(Count_Reset)RES(Carton_Count);`,
  },
  {
    id: "pump",
    name: "Pump station with level bands",
    summary: "Lead pump between level setpoints, high-high alarm, run-hour totaliser.",
    platform: "rockwell_logix",
    text: `// Lead pump P-101 starts above 80 % and stops below 20 %
GRT(Tank_Level,80.0)XIO(P101_Fault)XIC(Auto_Mode)OTL(P101_Run);
[LES(Tank_Level,20.0),XIC(P101_Fault)]OTU(P101_Run);
// High-high level alarm
GEQ(Tank_Level,95.0)OTE(LAHH_101);
// Run-hour totaliser
XIC(P101_Run)TON(Hour_Pulse,3600000,0);
XIC(Hour_Pulse.DN)ADD(P101_Hours,1,P101_Hours)RES(Hour_Pulse);`,
  },
  {
    id: "bottle",
    name: "Bottle filling line",
    summary: "Run latch, bottle-in-position latch, fill timer and conveyor restart delay. Try it in the simulator.",
    platform: "generic_iec",
    text: `// System run latch: Stop_PB and EStop_PB wired NC
[XIC(Start_PB),XIC(SRL)]XIC(Stop_PB)XIC(EStop_PB)OTE(SRL);
// Low tank level warning lamp
XIC(TankLevelLow_SNS)OTE(LowLevel_WARN);
// Bottle in position latch
XIC(BottleDetect_SNS)XIC(SRL)OTL(BIPL);
// Fill valve: running, bottle in position, tank not low, fill not finished
XIC(SRL)XIC(BIPL)XIO(TankLevelLow_SNS)XIO(FillTimer_T.DN)OTE(FillValve_OUT);
// Fill time 3 s
XIC(FillValve_OUT)TON(FillTimer_T,3000,0);
// Conveyor restart delay 0.5 s after the fill
XIC(FillTimer_T.DN)TON(ConveyorStartDelay_T,500,0);
XIC(ConveyorStartDelay_T.DN)OTU(BIPL);
// Conveyor runs when no bottle is in position
XIC(SRL)XIO(BIPL)OTE(Conveyor_MTR);`,
  },
  {
    id: "rslogix500",
    name: "RSLogix 500 screenshot (from your files)",
    summary: "The 3 rungs in ladder_logic_program_PLC1.webp, as the image pipeline reads them.",
    platform: "rockwell_slc",
    text: `0000: XIC(I:1/1)XIC(I:1/2)OTE(B:0/1);
0001: [XIC(I:1/3),XIC(B:0/1)]OTE(O:2/1);
0002: XIO(I:1/1)XIO(I:1/2)XIO(I:1/3)OTE(O:2/2);`,
  },
];

export function getSample(id: string | null | undefined): Sample | undefined {
  return SAMPLES.find((s) => s.id === id);
}
