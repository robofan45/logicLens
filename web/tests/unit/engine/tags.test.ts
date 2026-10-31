import { describe, expect, it } from "vitest";
import { parseProgram } from "../../../src/engine/parse";
import {
  TagTable,
  findInstances,
  nameHints,
  physicalClass,
  splitMember,
  tagKey,
  tagWords,
} from "../../../src/engine/tags";

describe("tag keys", () => {
  it("is case-insensitive and keeps the first spelling for display", () => {
    expect(tagKey("Motor_Run")).toBe(tagKey("MOTOR_RUN"));
    const t = new TagTable();
    t.see("Motor_Run");
    t.see("motor_run");
    expect(t.display(tagKey("MOTOR_RUN"))).toBe("Motor_Run");
    expect(t.display("UNSEEN")).toBe("UNSEEN");
  });
});

describe("member parsing", () => {
  it.each([
    ["T1.DN", "T1", "DN"],
    ["T4:0/DN", "T4:0", "DN"],
    ["T4:0.ACC", "T4:0", "ACC"],
    ["C5:0/DN", "C5:0", "DN"],
    ["Timer1.Q", "Timer1", "DN"],
    ["Timer1.ET", "Timer1", "ACC"],
    ["Cnt.CV", "Cnt", "ACC"],
    ["Cnt.PV", "Cnt", "PRE"],
    ["T1.tt", "T1", "TT"],
    ["T1.IN", "T1", "EN"],
    ["C1.OV", "C1", "OV"],
  ])("%s -> %s . %s", (raw, base, member) => {
    expect(splitMember(raw)).toEqual({ base, member });
  });

  it.each(["B3:0/1", "I:1/0", "Local:1:I.Data.0", "Out[0].5", "Motor.Run", "T1", "%Q0.1", '"T1.DN"'])(
    "%s is not a member access",
    (raw) => {
      expect(splitMember(raw)).toBeNull();
    },
  );
});

describe("physical classification by address", () => {
  it.each([
    ["I:1/0", "input"],
    ["I:1.0", "input"],
    ["%I0.0", "input"],
    ["%IX0.1", "input"],
    ["%IW64", "input"],
    ["Local:1:I.Data.0", "input"],
    ["Rack1:2:I.Data.3", "input"],
    ["O:2/1", "output"],
    ["%Q0.0", "output"],
    ["%QX1.2", "output"],
    ["Local:2:O.Data.3", "output"],
    ["B3:0/1", "internal"],
    ["B:0/1", "internal"],
    ["N7:0", "internal"],
    ["F8:1", "internal"],
    ["%M10.0", "internal"],
    ["%MW20", "internal"],
    ["Start_PB", "unknown"],
    ["Motor_Run", "unknown"],
  ])("%s -> %s", (raw, kind) => {
    expect(physicalClass(raw)).toBe(kind);
  });

  it("knows Mitsubishi X/Y/M only when told the platform", () => {
    expect(physicalClass("X0")).toBe("unknown");
    expect(physicalClass("X0", "mitsubishi")).toBe("input");
    expect(physicalClass("Y10", "mitsubishi")).toBe("output");
    expect(physicalClass("M100", "mitsubishi")).toBe("internal");
  });
});

describe("name hints", () => {
  it("splits words on separators and camelCase", () => {
    expect(tagWords("Start_PB")).toEqual(["START", "PB"]);
    expect(tagWords("MotorRun")).toEqual(["MOTOR", "RUN"]);
    expect(tagWords("E-STOP")).toEqual(["E", "STOP"]);
    expect(tagWords("conv1MotorOL")).toEqual(["CONV1", "MOTOR", "OL"]);
  });

  it.each([
    ["E_STOP", "estop"],
    ["ESTOP_PB", "estop"],
    ["EmergencyStop", "estop"],
    ["EMG_STOP", "estop"],
    ["ESD_Trip", "estop"],
    ["Stop_PB", "stop"],
    ["STP1", "stop"],
    ["Start_PB", "start"],
    ["StartButton", "start"],
    ["Motor_Run", "actuator"],
    ["PumpP101", "actuator"],
    ["FillValve_OUT", "actuator"],
    ["OL_Trip", "permissive"],
    ["TankLevelLow", "permissive"],
    ["Guard_Closed", "permissive"],
    ["Aux_Flag", "internal"],
    ["Step_State", "internal"],
  ])("%s carries the %s hint", (raw, hint) => {
    expect(nameHints(raw)).toContain(hint);
  });

  it("does not see actuators or stops in unrelated names", () => {
    expect(nameHints("Counter_Total")).toEqual([]);
    expect(nameHints("Lamp")).not.toContain("actuator");
    expect(nameHints("Bestop")).not.toContain("estop");
    expect(nameHints("Mopump")).toEqual([]);
  });
});

describe("instance detection", () => {
  it("finds timers and counters with every instruction that names them", () => {
    const p = parseProgram("XIC(A)TON(T1,500,0);\nXIC(T1.DN)CTU(C1,3,0);\nXIC(R)RES(C1);\nXIC(B)CTD(C1,3,0);");
    const inst = findInstances(p.rungs);
    expect(inst.get(tagKey("T1"))).toMatchObject({ kind: "timer", mnemonics: ["TON"] });
    expect(inst.get(tagKey("C1"))).toMatchObject({ kind: "counter", mnemonics: ["CTU", "CTD"] });
    expect(inst.get(tagKey("C1"))?.resets).toEqual(["r2i1"]);
  });
});
