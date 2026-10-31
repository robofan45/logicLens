// Ladder diagram rendered from the parsed program (not from a picture): rails, rungs, contacts,
// coils, box instructions and nested branches. Optional overlays: fault severity per instruction,
// simulator power flow, selection.

import { memo, useEffect, useRef, useState, type ReactNode } from "react";
import { SPEC, type Branch, type Instr, type InstrPower, type Rung, type Seq, type Severity } from "../../engine";

const CONTACT_W = 76;
const BOX_W = 132;
const ROW_H = 64;
const WIRE_Y = 30;
const EMPTY_LEG_H = 40;
const BR_PAD = 14;
const LINE_H = 13;
const LEFT = 58;
const RIGHT_PAD = 18;
const RUNG_GAP = 14;
const COMMENT_H = 18;

const COLORS = {
  wire: "#64748b",
  on: "#22c55e",
  text: "#cbd5e1",
  dim: "#94a3b8",
  rail: "#94a3b8",
  box: "#1e293b",
  select: "#22d3ee",
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#60a5fa",
} as const;

const CONTACTS = new Set(["XIC", "XIO", "P", "N", "LBL"]);
const COILS = new Set(["OTE", "OTL", "OTU", "NCOIL", "RES", "JMP", "MCR", "END", "NOP"]);
const COIL_MARK: Record<string, string> = { OTL: "L", OTU: "U", NCOIL: "/", RES: "RES", JMP: "JMP", MCR: "MCR", END: "END", NOP: "NOP" };

function operandLabels(ins: Instr): string[] {
  const n = ins.operands.length;
  switch (ins.mnemonic) {
    case "TON": case "TOF": case "RTO":
      return n === 4 ? ["Timer", "Base", "Preset", "Accum"] : n === 3 ? ["Timer", "Preset", "Accum"] : ["Timer", "PT"];
    case "TP":
      return ["Timer", "PT", "Accum"];
    case "CTU": case "CTD":
      return ["Counter", "Preset", "Accum"];
    case "CTUD":
      return ["Counter", "Preset", "CD input"];
    case "ADD": case "SUB": case "MUL": case "DIV": case "AND": case "OR": case "XOR":
      return ["Source A", "Source B", "Dest"];
    case "MOV": case "NOT":
      return ["Source", "Dest"];
    case "EQU": case "NEQ": case "GRT": case "GEQ": case "LES": case "LEQ":
      return ["Source A", "Source B"];
    case "LIM":
      return ["Low", "Test", "High"];
    case "OSR": case "OSF":
      return ["Storage", "Output"];
    case "ONS":
      return ["Storage"];
    case "JSR":
      return ["Routine", ...Array.from({ length: Math.max(0, n - 1) }, (_, i) => `Param ${i + 1}`)];
    default:
      return [];
  }
}

const isBox = (ins: Instr) => !CONTACTS.has(ins.mnemonic) && !COILS.has(ins.mnemonic);
const short = (s: string, max = 13) => (s.length > max ? `${s.slice(0, max - 1)}…` : s);

interface Size { w: number; h: number }

function boxHeight(ins: Instr): number {
  return 18 + Math.max(1, operandLabels(ins).length) * LINE_H + 6;
}

function measureInstr(ins: Instr): Size {
  if (!isBox(ins)) return { w: CONTACT_W, h: ROW_H };
  return { w: BOX_W, h: Math.max(ROW_H, WIRE_Y - 12 + boxHeight(ins) + 10) };
}

function measureSeq(seq: Seq): Size {
  if (!seq.items.length) return { w: 24, h: EMPTY_LEG_H };
  let w = 0;
  let h = 0;
  for (const item of seq.items) {
    const s = item.kind === "instr" ? measureInstr(item) : measureBranch(item);
    w += s.w;
    h = Math.max(h, s.h);
  }
  return { w, h };
}

function measureBranch(b: Branch): Size {
  let w = 0;
  let h = 0;
  for (const leg of b.legs) {
    const s = measureSeq(leg);
    w = Math.max(w, s.w);
    h += s.h;
  }
  return { w: w + 2 * BR_PAD, h };
}

function onlyOutputs(item: Instr | Branch): boolean {
  if (item.kind === "instr") return SPEC[item.mnemonic][2] === "out";
  return item.legs.length > 0 && item.legs.every((leg) => leg.items.length > 0 && leg.items.every(onlyOutputs));
}

/** Split a rung into the condition part (drawn from the left) and trailing outputs (right-aligned). */
function splitRung(rung: Rung): { prefix: Seq; suffix: Seq } {
  const items = rung.body.items;
  let k = items.length;
  while (k > 0 && onlyOutputs(items[k - 1])) k--;
  return { prefix: { kind: "seq", items: items.slice(0, k) }, suffix: { kind: "seq", items: items.slice(k) } };
}

export interface LadderDiagramProps {
  rungs: Rung[];
  /** instrId -> worst severity of a finding that points at it */
  highlights?: Record<string, Severity>;
  /** simulator power, instrId -> rung-condition in/out */
  power?: Record<string, InstrPower>;
  selectedId?: string | null;
  onSelect?: (instrId: string) => void;
  maxRungs?: number;
  /** id prefix so several diagrams can live on one page */
  idPrefix?: string;
}

interface Ctx {
  out: ReactNode[];
  props: LadderDiagramProps;
  key: number;
}

function wire(ctx: Ctx, x1: number, y1: number, x2: number, y2: number, on?: boolean) {
  if (x1 === x2 && y1 === y2) return;
  ctx.out.push(
    <line key={ctx.key++} x1={x1} y1={y1} x2={x2} y2={y2} stroke={on ? COLORS.on : COLORS.wire} strokeWidth={on ? 2.5 : 1.5} />,
  );
}

function drawInstr(ctx: Ctx, ins: Instr, x: number, y: number, size: Size) {
  const { highlights, power, selectedId, onSelect } = ctx.props;
  const wy = y + WIRE_Y;
  const p = power?.[ins.id];
  const role = SPEC[ins.mnemonic][2];
  const inOn = p?.in;
  const symOn = role === "in" ? p?.out : p?.in;
  const outOn = p?.out;
  const sev = highlights?.[ins.id];
  const selected = selectedId === ins.id;
  const color = symOn ? COLORS.on : COLORS.text;
  const parts: ReactNode[] = [];
  const cx = x + size.w / 2;
  const tag = ins.operands[0]?.raw ?? "";
  let k = 0;

  if (sev || selected) {
    parts.push(
      <rect key={k++} x={x + 3} y={y + 2} width={size.w - 6} height={size.h - 4} rx={6}
        fill={sev ? COLORS[sev] : COLORS.select} fillOpacity={0.1}
        stroke={selected ? COLORS.select : COLORS[sev as Severity]} strokeWidth={selected ? 2 : 1.25} strokeDasharray={selected ? undefined : "4 3"} />,
    );
  }

  if (CONTACTS.has(ins.mnemonic)) {
    wire(ctx, x, wy, cx - 9, wy, inOn);
    wire(ctx, cx + 9, wy, x + size.w, wy, outOn);
    parts.push(<line key={k++} x1={cx - 9} y1={wy - 12} x2={cx - 9} y2={wy + 12} stroke={color} strokeWidth={2} />);
    parts.push(<line key={k++} x1={cx + 9} y1={wy - 12} x2={cx + 9} y2={wy + 12} stroke={color} strokeWidth={2} />);
    if (ins.mnemonic === "XIO") parts.push(<line key={k++} x1={cx - 6} y1={wy + 9} x2={cx + 6} y2={wy - 9} stroke={color} strokeWidth={1.75} />);
    if (ins.mnemonic === "P" || ins.mnemonic === "N" || ins.mnemonic === "LBL") {
      parts.push(<text key={k++} x={cx} y={wy + 4} textAnchor="middle" fontSize={ins.mnemonic === "LBL" ? 8 : 11} fill={color} fontFamily="Fira Code, monospace">{ins.mnemonic}</text>);
    }
    parts.push(<text key={k++} x={cx} y={y + 12} textAnchor="middle" fontSize={10.5} fill={COLORS.text} fontFamily="Fira Code, monospace">{short(tag)}</text>);
  } else if (COILS.has(ins.mnemonic)) {
    wire(ctx, x, wy, cx - 11, wy, inOn);
    wire(ctx, cx + 11, wy, x + size.w, wy, outOn);
    parts.push(<path key={k++} d={`M ${cx - 6} ${wy - 12} Q ${cx - 15} ${wy} ${cx - 6} ${wy + 12}`} fill="none" stroke={color} strokeWidth={2} />);
    parts.push(<path key={k++} d={`M ${cx + 6} ${wy - 12} Q ${cx + 15} ${wy} ${cx + 6} ${wy + 12}`} fill="none" stroke={color} strokeWidth={2} />);
    const mark = COIL_MARK[ins.mnemonic];
    if (mark) parts.push(<text key={k++} x={cx} y={wy + 3.5} textAnchor="middle" fontSize={mark.length > 1 ? 7.5 : 11} fill={color} fontFamily="Fira Code, monospace">{mark}</text>);
    if (tag) parts.push(<text key={k++} x={cx} y={y + 12} textAnchor="middle" fontSize={10.5} fill={COLORS.text} fontFamily="Fira Code, monospace">{short(tag)}</text>);
  } else {
    const labels = operandLabels(ins);
    const bh = boxHeight(ins);
    const top = wy - 12;
    const bx = x + 8;
    const bw = size.w - 16;
    wire(ctx, x, wy, bx, wy, inOn);
    wire(ctx, bx + bw, wy, x + size.w, wy, outOn);
    parts.push(<rect key={k++} x={bx} y={top} width={bw} height={bh} rx={3} fill={COLORS.box} stroke={symOn ? COLORS.on : COLORS.dim} strokeWidth={1.5} />);
    parts.push(<text key={k++} x={bx + 6} y={top + 12} fontSize={10.5} fontWeight={700} fill={symOn ? COLORS.on : "#e2e8f0"} fontFamily="Fira Code, monospace">{ins.mnemonic}</text>);
    labels.forEach((label, i) => {
      const value = ins.operands[i]?.raw ?? "";
      const ly = top + 18 + (i + 1) * LINE_H - 3;
      parts.push(<text key={k++} x={bx + 6} y={ly} fontSize={8.5} fill={COLORS.dim} fontFamily="Inter, sans-serif">{label}</text>);
      parts.push(<text key={k++} x={bx + bw - 6} y={ly} textAnchor="end" fontSize={9.5} fill={COLORS.text} fontFamily="Fira Code, monospace">{short(value, 11)}</text>);
    });
  }

  const label = `${ins.mnemonic}(${ins.operands.map((o) => o.raw).join(", ")})${sev ? `, ${sev} finding` : ""}`;
  const interactive = !!onSelect;
  ctx.out.push(
    <g
      key={ctx.key++}
      data-instr={ins.id}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? label : undefined}
      aria-pressed={interactive ? selected : undefined}
      style={interactive ? { cursor: "pointer", outline: "none" } : undefined}
      onClick={interactive ? () => onSelect?.(ins.id) : undefined}
      onKeyDown={interactive ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(ins.id); } } : undefined}
    >
      <title>{label}</title>
      <rect x={x} y={y} width={size.w} height={size.h} fill="transparent" />
      {parts}
    </g>,
  );
}

function drawSeq(ctx: Ctx, seq: Seq, x: number, y: number): number {
  if (!seq.items.length) {
    wire(ctx, x, y + WIRE_Y, x + 24, y + WIRE_Y);
    return x + 24;
  }
  let cx = x;
  for (const item of seq.items) {
    if (item.kind === "instr") {
      const s = measureInstr(item);
      drawInstr(ctx, item, cx, y, s);
      cx += s.w;
    } else {
      cx = drawBranch(ctx, item, cx, y);
    }
  }
  return cx;
}

function drawBranch(ctx: Ctx, b: Branch, x: number, y: number): number {
  const size = measureBranch(b);
  const xl = x + BR_PAD / 2;
  const xr = x + size.w - BR_PAD / 2;
  let ly = y;
  const wireYs: number[] = [];
  for (const leg of b.legs) {
    const ls = measureSeq(leg);
    const wy = ly + WIRE_Y;
    wireYs.push(wy);
    wire(ctx, xl, wy, x + BR_PAD, wy);
    const end = drawSeq(ctx, leg, x + BR_PAD, ly);
    wire(ctx, end, wy, xr, wy);
    ly += ls.h;
  }
  wire(ctx, x, y + WIRE_Y, xl, y + WIRE_Y);
  wire(ctx, xr, y + WIRE_Y, x + size.w, y + WIRE_Y);
  const top = wireYs[0];
  const bottom = wireYs[wireYs.length - 1];
  if (bottom > top) {
    ctx.out.push(<line key={ctx.key++} x1={xl} y1={top} x2={xl} y2={bottom} stroke={COLORS.wire} strokeWidth={1.5} />);
    ctx.out.push(<line key={ctx.key++} x1={xr} y1={top} x2={xr} y2={bottom} stroke={COLORS.wire} strokeWidth={1.5} />);
  }
  return x + size.w;
}

function useAvailableWidth(): [React.RefObject<HTMLDivElement>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

function LadderDiagramImpl(props: LadderDiagramProps) {
  const { rungs, maxRungs = 150 } = props;
  const [wrapRef, available] = useAvailableWidth();
  const shown = rungs.slice(0, maxRungs);
  const layouts = shown.map((r) => {
    const { prefix, suffix } = splitRung(r);
    const ps = prefix.items.length ? measureSeq(prefix) : { w: 0, h: ROW_H };
    const ss = suffix.items.length ? measureSeq(suffix) : { w: 0, h: ROW_H };
    return { r, prefix, suffix, ps, ss, h: Math.max(ps.h, ss.h) + (r.comment ? COMMENT_H : 0) };
  });
  const natural = Math.max(360, ...layouts.map((l) => LEFT + 10 + l.ps.w + 36 + l.ss.w + 10 + RIGHT_PAD));
  const width = Math.max(natural, Math.floor(available));
  const railR = width - RIGHT_PAD;
  const ctx: Ctx = { out: [], props, key: 0 };
  let y = 10;
  for (const l of layouts) {
    const top = y + (l.r.comment ? COMMENT_H : 0);
    if (l.r.comment) {
      ctx.out.push(
        <text key={ctx.key++} x={LEFT + 8} y={y + 12} fontSize={10.5} fill="#7dd3fc" fontStyle="italic" fontFamily="Inter, sans-serif">
          {short(l.r.comment.split("\n").join(" · "), Math.floor((railR - LEFT) / 6))}
        </text>,
      );
    }
    ctx.out.push(
      <text key={ctx.key++} x={LEFT - 10} y={top + WIRE_Y + 4} textAnchor="end" fontSize={11} fill={COLORS.dim} fontFamily="Fira Code, monospace">
        {String(l.r.number).padStart(4, "0")}
      </text>,
    );
    const wy = top + WIRE_Y;
    let end = LEFT;
    if (l.prefix.items.length) {
      wire(ctx, LEFT, wy, LEFT + 10, wy);
      end = drawSeq(ctx, l.prefix, LEFT + 10, top);
    }
    if (l.suffix.items.length) {
      const sx = railR - 10 - l.ss.w;
      wire(ctx, end, wy, sx, wy, ctx.props.power?.[firstId(l.suffix)]?.in);
      const send = drawSeq(ctx, l.suffix, sx, top);
      wire(ctx, send, wy, railR, wy);
    } else {
      wire(ctx, end, wy, railR, wy);
    }
    y += l.h + RUNG_GAP;
  }
  const height = Math.max(y, 80);
  return (
    <div ref={wrapRef} className="overflow-x-auto">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Ladder diagram, ${rungs.length} rung${rungs.length === 1 ? "" : "s"}`}
        style={{ minWidth: width, display: "block" }}
      >
        <line x1={LEFT} y1={4} x2={LEFT} y2={height - 4} stroke={COLORS.rail} strokeWidth={3} />
        <line x1={railR} y1={4} x2={railR} y2={height - 4} stroke={COLORS.rail} strokeWidth={3} />
        {ctx.out}
      </svg>
      {rungs.length > shown.length && (
        <p className="text-slate-500 mt-2" style={{ fontSize: "0.75rem" }}>
          Showing the first {shown.length} of {rungs.length} rungs.
        </p>
      )}
    </div>
  );
}

function firstId(seq: Seq): string {
  for (const item of seq.items) {
    if (item.kind === "instr") return item.id;
    for (const leg of item.legs) {
      const id = firstId(leg);
      if (id) return id;
    }
  }
  return "";
}

export const LadderDiagram = memo(LadderDiagramImpl);
