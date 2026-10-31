// LogicLens Ladder Text (LLT) parser - TypeScript port of contract/python/logiclens_ladder.py.
//
// The grammar, limits and error codes are defined in contract/README.md and pinned by
// contract/ladder_cases.json, which this parser and the Python reference both pass.
// It never throws on bad input: it returns every valid rung plus a list of errors.
//
// To match Python exactly, offsets and lengths count Unicode code points (not UTF-16 units),
// whitespace follows str.isspace(), lines split like str.splitlines(), and `\d` accepts any
// Unicode decimal digit, as Python's `re` does for str patterns.

import type {
  Branch,
  Instr,
  Mnemonic,
  Operand,
  ParseError,
  ParseErrorCode,
  ParseResult,
  Role,
  Rung,
  Seq,
} from "./types";

export const LIMITS = {
  program_chars: 200_000,
  rungs: 2_000,
  rung_chars: 4_000,
  instructions: 256,
  depth: 16,
  operands: 8,
  operand_chars: 120,
} as const;

export const ALIASES: Readonly<Record<string, Mnemonic>> = {
  NO: "XIC",
  NC: "XIO",
  COIL: "OTE",
  OUT: "OTE",
  SET: "OTL",
  S: "OTL",
  RESET: "OTU",
  R: "OTU",
};

/** canonical mnemonic -> [min operands, max operands, role] */
export const SPEC: Readonly<Record<Mnemonic, readonly [number, number, Role]>> = {
  XIC: [1, 1, "in"], XIO: [1, 1, "in"], ONS: [1, 1, "in"], P: [1, 1, "in"], N: [1, 1, "in"],
  EQU: [2, 2, "in"], NEQ: [2, 2, "in"], GRT: [2, 2, "in"], GEQ: [2, 2, "in"],
  LES: [2, 2, "in"], LEQ: [2, 2, "in"], LIM: [3, 3, "in"], AFI: [0, 0, "in"], LBL: [1, 1, "in"],
  OTE: [1, 1, "out"], OTL: [1, 1, "out"], OTU: [1, 1, "out"], NCOIL: [1, 1, "out"],
  OSR: [2, 2, "out"], OSF: [2, 2, "out"],
  TON: [2, 4, "out"], TOF: [2, 4, "out"], RTO: [2, 4, "out"], TP: [2, 3, "out"],
  CTU: [2, 3, "out"], CTD: [2, 3, "out"], CTUD: [2, 3, "out"], RES: [1, 1, "out"],
  ADD: [3, 3, "out"], SUB: [3, 3, "out"], MUL: [3, 3, "out"], DIV: [3, 3, "out"],
  AND: [3, 3, "out"], OR: [3, 3, "out"], XOR: [3, 3, "out"],
  MOV: [2, 2, "out"], NOT: [2, 2, "out"],
  JMP: [1, 1, "out"], JSR: [1, 8, "out"], MCR: [0, 0, "out"], END: [0, 0, "out"], NOP: [0, 0, "out"],
};

export function roleOf(m: Mnemonic): Role {
  return SPEC[m][2];
}

// ------------------------------------------------------------------ Python-compatible helpers
/** Characters for which Python's str.isspace() is true. */
const PY_WS = "\\t\\n\\v\\f\\r \\x1c-\\x1f\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WS_ONE = new RegExp(`^[${PY_WS}]$`, "u");
const ALPHA_ONE = /^\p{L}$/u;
const ALNUM_ONE = /^[\p{L}\p{N}]$/u;
const ND_ONE = /^\p{Nd}$/u;

const isSpace = (c: string | undefined): boolean => c !== undefined && WS_ONE.test(c);
const isAlpha = (c: string): boolean => ALPHA_ONE.test(c);
const isAlnum = (c: string): boolean => ALNUM_ONE.test(c);

function pyStrip(s: string): string {
  const a = Array.from(s);
  let i = 0;
  let j = a.length;
  while (i < j && isSpace(a[i])) i++;
  while (j > i && isSpace(a[j - 1])) j--;
  return a.slice(i, j).join("");
}

function lstripLen(a: string[]): number {
  let i = 0;
  while (i < a.length && isSpace(a[i])) i++;
  return i;
}

/** Number of code points (what Python's len() returns). */
function cpLen(s: string): number {
  let n = 0;
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
      const d = s.charCodeAt(i + 1);
      if (d >= 0xdc00 && d <= 0xdfff) i++;
    }
    n++;
  }
  return n;
}

/** Python str.splitlines() (no keepends). */
function splitLines(text: string): string[] {
  const out: string[] = [];
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    if (c === 13) {
      out.push(text.slice(start, i));
      if (text.charCodeAt(i + 1) === 10) i++;
      start = i + 1;
    } else if (c === 10 || c === 11 || c === 12 || c === 0x1c || c === 0x1d || c === 0x1e || c === 0x85 || c === 0x2028 || c === 0x2029) {
      out.push(text.slice(start, i));
      start = i + 1;
    }
  }
  if (start < text.length) out.push(text.slice(start));
  return out;
}

/** Decimal value of one Unicode Nd code point (Nd runs are contiguous blocks of ten). */
function digitValue(ch: string): number {
  const cp = ch.codePointAt(0)!;
  if (cp >= 48 && cp <= 57) return cp - 48;
  let start = cp;
  while (start > 0 && ND_ONE.test(String.fromCodePoint(start - 1))) start--;
  return (cp - start) % 10;
}

/** Replace every Unicode decimal digit with its ASCII digit. */
function asciiDigits(s: string): string {
  let out = "";
  for (const ch of s) out += ND_ONE.test(ch) ? String(digitValue(ch)) : ch;
  return out;
}

function decompose(x: number): { mant: bigint; exp: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const e = (hi >>> 20) & 0x7ff;
  let mant = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exp: number;
  if (e === 0) {
    exp = -1074;
  } else {
    mant |= 1n << 52n;
    exp = e - 1075;
  }
  return { mant: hi >>> 31 ? -mant : mant, exp };
}

/** Python's round(x, nd): exact round-half-even of the binary value, then nearest double. */
export function pyRound(x: number, nd: number): number {
  if (!Number.isFinite(x) || x === 0) return x;
  const { mant, exp } = decompose(x);
  const neg = mant < 0n;
  const m = neg ? -mant : mant;
  const scale = 10n ** BigInt(nd);
  let q: bigint;
  if (exp >= 0) {
    q = m * (1n << BigInt(exp)) * scale;
  } else {
    const num = m * scale;
    const den = 1n << BigInt(-exp);
    q = num / den;
    const twice = 2n * (num % den);
    if (twice > den || (twice === den && (q & 1n) === 1n)) q += 1n;
  }
  return Number(`${neg ? "-" : ""}${q}e-${nd}`);
}

// ------------------------------------------------------------------ operand typing
const WS = `[${PY_WS}]`;
const LABEL_RE = new RegExp(`^${WS}*(?:(?:rung|network|n)${WS}*)?(\\p{Nd}+)${WS}*[:.)]${WS}*`, "iu");
const BARE_N_RE = new RegExp(`^${WS}*N${WS}*:${WS}*`, "iu");
const NUM_RE = /^[+-]?(?:\p{Nd}+(?:\.\p{Nd}*)?|\.\p{Nd}+)(?:[eE][+-]?\p{Nd}+)?$/u;
const RADIX_RE = /^(2|8|16)#([0-9A-Fa-f_]+)$/;
const RADIX_PREFIX_RE = /^\p{Nd}+#/u;
const TIME_RE = /^(?:T|TIME)#(-?)([0-9a-zA-Z_.]+)$/i;
const TIME_BODY_RE = /^(?:\d+(?:\.\d+)?(?:ms|d|h|m|s))+$/i;
const TIME_PART_RE = /(\d+(?:\.\d+)?)(ms|d|h|m|s)/gi;
const TAG_RE = /^(?:"[^"\x00-\x1f]{1,118}"|[A-Za-z0-9_%#][A-Za-z0-9_:./[\]%#]*)$/u;
const UNIT_MS: Record<string, number> = { d: 86_400_000, h: 3_600_000, m: 60_000, s: 1_000, ms: 1 };

/** Milliseconds for an IEC time literal such as T#1m30s, or null if it is not one. */
export function timeLiteralMs(raw: string): number | null {
  const m = TIME_RE.exec(raw);
  if (!m) return null;
  const body = m[2].replace(/_/g, "");
  if (!body || !TIME_BODY_RE.test(body)) return null;
  let total = 0;
  for (const part of body.matchAll(TIME_PART_RE)) total += Number(part[1]) * UNIT_MS[part[2].toLowerCase()];
  return m[1] === "-" ? -total : total;
}

/** Type an operand; null means the text is not a valid operand. */
export function classifyOperand(raw: string): Operand | null {
  if (raw === "?") return { raw, type: "unknown" };
  if (NUM_RE.test(raw)) return { raw, type: "number", value: Number(asciiDigits(raw)) };
  const rm = RADIX_RE.exec(raw);
  if (rm === null && RADIX_PREFIX_RE.test(raw)) return null;
  if (rm) {
    const digits = rm[2].replace(/_/g, "");
    const prefix = rm[1] === "16" ? "0x" : rm[1] === "8" ? "0o" : "0b";
    try {
      if (!digits) return null;
      return { raw, type: "number", value: Number(BigInt(prefix + digits)) };
    } catch {
      return null;
    }
  }
  if (raw.slice(0, 2).toUpperCase() === "T#" || raw.slice(0, 5).toUpperCase() === "TIME#") {
    const ms = timeLiteralMs(raw);
    return ms === null ? null : { raw, type: "time", value: ms };
  }
  if (TAG_RE.test(raw)) return { raw, type: "tag" };
  return null;
}

// ------------------------------------------------------------------ rung parser
class RungError {
  constructor(
    readonly code: ParseErrorCode,
    readonly message: string,
    readonly offset: number,
  ) {}
}

class RungParser {
  private readonly s: string[];
  private i = 0;
  count = 0;

  constructor(text: string) {
    this.s = Array.from(text);
  }

  private peek(): string | undefined {
    return this.s[this.i];
  }

  private skipWs(): void {
    while (this.i < this.s.length && isSpace(this.s[this.i])) this.i++;
  }

  parse(): Seq {
    const seq = this.seq(0, false);
    this.skipWs();
    if (this.i < this.s.length) throw new RungError("E_SYNTAX", `unexpected '${this.s[this.i]}'`, this.i);
    if (this.count === 0) throw new RungError("E_EMPTY_RUNG", "rung has no instructions", 0);
    return seq;
  }

  private seq(depth: number, inBranch: boolean): Seq {
    const items: (Instr | Branch)[] = [];
    for (;;) {
      this.skipWs();
      const c = this.peek();
      if (c === undefined) {
        if (inBranch) throw new RungError("E_UNBALANCED", "'[' is never closed", this.i);
        return { kind: "seq", items };
      }
      if (c === "[") {
        if (depth + 1 > LIMITS.depth) {
          throw new RungError("E_LIMIT", `branches nested deeper than ${LIMITS.depth}`, this.i);
        }
        const start = this.i;
        this.i++;
        const legs = [this.seq(depth + 1, true)];
        while (this.peek() === ",") {
          this.i++;
          legs.push(this.seq(depth + 1, true));
        }
        if (this.peek() !== "]") throw new RungError("E_UNBALANCED", "'[' is never closed", start);
        this.i++;
        items.push({ kind: "branch", legs });
      } else if (c === "," || c === "]") {
        if (inBranch) return { kind: "seq", items };
        if (c === "]") throw new RungError("E_UNBALANCED", "']' without a matching '['", this.i);
        throw new RungError("E_SYNTAX", "',' outside a branch", this.i);
      } else if (c === ")") {
        throw new RungError("E_UNBALANCED", "')' without a matching '('", this.i);
      } else if (isAlpha(c) || c === "_") {
        items.push(this.instr());
      } else {
        throw new RungError("E_SYNTAX", `unexpected '${c}'`, this.i);
      }
    }
  }

  private instr(): Instr {
    const start = this.i;
    while (this.i < this.s.length && (isAlnum(this.s[this.i]) || this.s[this.i] === "_")) this.i++;
    const word = this.s.slice(start, this.i).join("");
    this.skipWs();
    if (this.peek() !== "(") throw new RungError("E_SYNTAX", `expected '(' after ${word}`, this.i);
    const upper = word.toUpperCase();
    const mnemonic = (ALIASES[upper] ?? upper) as Mnemonic;
    if (!Object.prototype.hasOwnProperty.call(SPEC, mnemonic)) {
      throw new RungError("E_UNKNOWN_MNEMONIC", `unknown instruction '${word}'`, start);
    }
    const operands = this.operands();
    if (operands.length > LIMITS.operands) {
      throw new RungError("E_LIMIT", `more than ${LIMITS.operands} operands`, start);
    }
    const [lo, hi] = SPEC[mnemonic];
    if (operands.length < lo || operands.length > hi) {
      const want = lo === hi ? String(lo) : `${lo}-${hi}`;
      throw new RungError("E_ARITY", `${mnemonic} takes ${want} operands, got ${operands.length}`, start);
    }
    this.count++;
    if (this.count > LIMITS.instructions) {
      throw new RungError("E_LIMIT", `more than ${LIMITS.instructions} instructions`, start);
    }
    return { kind: "instr", id: "", mnemonic, operands, index: this.count - 1, col: start };
  }

  private operands(): Operand[] {
    const openAt = this.i;
    this.i++; // consume '('
    const parts: [string, number][] = [];
    let depthP = 0;
    let depthB = 0;
    let curStart = this.i;
    for (;;) {
      const c = this.peek();
      if (c === undefined) throw new RungError("E_UNBALANCED", "'(' is never closed", openAt);
      if (c === "(") {
        depthP++;
      } else if (c === ")") {
        if (depthP === 0) {
          parts.push([this.s.slice(curStart, this.i).join(""), curStart]);
          this.i++;
          break;
        }
        depthP--;
      } else if (c === "[") {
        depthB++;
      } else if (c === "]") {
        depthB = Math.max(0, depthB - 1);
      } else if (c === "," && depthP === 0 && depthB === 0) {
        parts.push([this.s.slice(curStart, this.i).join(""), curStart]);
        curStart = this.i + 1;
      }
      this.i++;
    }
    if (parts.length === 1 && pyStrip(parts[0][0]) === "") return [];
    const out: Operand[] = [];
    for (const [raw, at] of parts) {
      const text = pyStrip(raw);
      if (!text) throw new RungError("E_EMPTY_OPERAND", "empty operand", at);
      if (cpLen(text) > LIMITS.operand_chars) {
        throw new RungError("E_LIMIT", `operand longer than ${LIMITS.operand_chars} characters`, at);
      }
      const op = classifyOperand(text);
      if (op === null) throw new RungError("E_SYNTAX", `invalid operand '${Array.from(text).slice(0, 40).join("")}'`, at);
      out.push(op);
    }
    return out;
  }
}

// ------------------------------------------------------------------ program level
function splitInline(line: string[]): [string[], string | null] {
  let depth = 0;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === "(") depth++;
    else if (c === ")") depth = Math.max(0, depth - 1);
    else if (c === "/" && depth === 0 && line[i + 1] === "/") return [line.slice(0, i), pyStrip(line.slice(i + 2).join(""))];
  }
  return [line, null];
}

function segments(code: string[], offset: number): [string[], number][] {
  const out: [string[], number][] = [];
  let depth = 0;
  let start = offset;
  for (let i = offset; i < code.length; i++) {
    const c = code[i];
    if (c === "(") depth++;
    else if (c === ")") depth = Math.max(0, depth - 1);
    else if (c === ";" && depth === 0) {
      out.push([code.slice(start, i), start]);
      start = i + 1;
    }
  }
  out.push([code.slice(start), start]);
  return out;
}

function perr(code: ParseErrorCode, message: string, line: number, col: number): ParseError {
  return { code, message, line, col };
}

/** Parse one rung body (label already removed, no trailing ';'). */
export function parseRungText(
  text: string,
  number = 0,
  comment: string | null = null,
  line = 1,
  colOffset = 0,
): { rung: Rung | null; error: ParseError | null } {
  if (cpLen(text) > LIMITS.rung_chars) {
    return { rung: null, error: perr("E_LIMIT", `rung longer than ${LIMITS.rung_chars} characters`, line, colOffset + 1) };
  }
  const p = new RungParser(text);
  let body: Seq;
  try {
    body = p.parse();
  } catch (e) {
    if (e instanceof RungError) return { rung: null, error: perr(e.code, e.message, line, colOffset + e.offset + 1) };
    throw e;
  }
  const rung: Rung = { number, comment, body, line, text: "" };
  rung.text = printRung(rung);
  return { rung, error: null };
}

function assignIds(rungs: Rung[]): void {
  rungs.forEach((rung, idx) => {
    for (const ins of iterInstructions(rung.body)) ins.id = `r${idx}i${ins.index}`;
  });
}

function result(rungs: Rung[], errors: ParseError[]): ParseResult {
  assignIds(rungs);
  return { ok: errors.length === 0, rungs, errors };
}

/** Parse a whole LLT program. Never throws. */
export function parseProgram(text: string): ParseResult {
  if (typeof text !== "string") return result([], [perr("E_SYNTAX", "program must be text", 0, 0)]);
  if (cpLen(text) > LIMITS.program_chars) {
    return result([], [perr("E_LIMIT", `program longer than ${LIMITS.program_chars} characters`, 0, 0)]);
  }
  const rungs: Rung[] = [];
  const errors: ParseError[] = [];
  let pending: string[] = [];
  let nextNumber = 0;
  let total = 0;
  const lines = splitLines(text);
  for (let li = 0; li < lines.length; li++) {
    const lineNo = li + 1;
    const raw = lines[li];
    const stripped = pyStrip(raw);
    if (!stripped) continue;
    if (stripped.startsWith("#")) {
      const note = pyStrip(stripped.slice(1));
      if (note) pending.push(note);
      continue;
    }
    const [codeArr, inline] = splitInline(Array.from(raw));
    const code = codeArr.join("");
    if (!pyStrip(code)) {
      if (inline) pending.push(inline);
      continue;
    }
    let labelNum: number | null = null;
    let offset = 0;
    const m = LABEL_RE.exec(code);
    if (m) {
      labelNum = Number(asciiDigits(m[1]));
      offset = cpLen(m[0]);
    } else {
      const mb = BARE_N_RE.exec(code);
      if (mb) offset = cpLen(mb[0]);
    }
    const segs = segments(codeArr, offset).filter(([s]) => pyStrip(s.join("")) !== "");
    if (segs.length === 0) {
      if (labelNum !== null) {
        errors.push(perr("E_EMPTY_RUNG", "label without a rung", lineNo, 1));
        nextNumber = labelNum + 1;
      }
      continue;
    }
    for (let k = 0; k < segs.length; k++) {
      const [seg, at] = segs[k];
      total++;
      if (total > LIMITS.rungs) {
        errors.push(perr("E_LIMIT", `more than ${LIMITS.rungs} rungs`, lineNo, 0));
        return result(rungs, errors);
      }
      const number = k === 0 && labelNum !== null ? labelNum : nextNumber;
      nextNumber = number + 1;
      let parts = k === 0 ? pending : [];
      if (k === 0) pending = [];
      if (k === segs.length - 1 && inline) parts = [...parts, inline];
      const comment = parts.length ? parts.join("\n") : null;
      const lead = lstripLen(seg);
      const { rung, error } = parseRungText(pyStrip(seg.join("")), number, comment, lineNo, at + lead);
      if (error) errors.push(error);
      else if (rung) rungs.push(rung);
    }
  }
  return result(rungs, errors);
}

/** Instructions of a sequence in text order (depth-first, left to right). */
export function* iterInstructions(seq: Seq): Generator<Instr> {
  for (const item of seq.items) {
    if (item.kind === "instr") yield item;
    else for (const leg of item.legs) yield* iterInstructions(leg);
  }
}

export function printSeq(seq: Seq): string {
  let out = "";
  for (const item of seq.items) {
    if (item.kind === "instr") out += `${item.mnemonic}(${item.operands.map((o) => o.raw).join(",")})`;
    else out += `[${item.legs.map(printSeq).join(",")}]`;
  }
  return out;
}

export function printRung(rung: Pick<Rung, "body">): string {
  return `${printSeq(rung.body)};`;
}

export function printProgram(rungs: Pick<Rung, "body" | "comment">[], comments = true): string {
  const lines: string[] = [];
  for (const r of rungs) {
    if (comments && r.comment) for (const c of r.comment.split("\n")) lines.push(`// ${c}`);
    lines.push(printRung(r));
  }
  return lines.join("\n");
}

/** Preset in ms for TON/TOF/RTO/TP, null if it is a tag or unknown. */
export function timerPresetMs(ins: Instr): number | null {
  if (!["TON", "TOF", "RTO", "TP"].includes(ins.mnemonic)) return null;
  const ops = ins.operands;
  if (ops.length === 4) {
    const [, base, pre] = ops;
    if (base.type === "number" && pre.type === "number") return pyRound(base.value! * pre.value! * 1000, 6);
    return null;
  }
  const pre = ops[1];
  if (pre.type === "time" || pre.type === "number") return pre.value!;
  return null;
}
