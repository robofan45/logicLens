// LogicLens Ladder Text (LLT) AST. Mirrors contract/python/logiclens_ladder.py.

export type Mnemonic =
  | "XIC" | "XIO" | "ONS" | "P" | "N"
  | "EQU" | "NEQ" | "GRT" | "GEQ" | "LES" | "LEQ" | "LIM" | "AFI" | "LBL"
  | "OTE" | "OTL" | "OTU" | "NCOIL" | "OSR" | "OSF"
  | "TON" | "TOF" | "RTO" | "TP" | "CTU" | "CTD" | "CTUD" | "RES"
  | "ADD" | "SUB" | "MUL" | "DIV" | "AND" | "OR" | "XOR" | "MOV" | "NOT"
  | "JMP" | "JSR" | "MCR" | "END" | "NOP";

export type Role = "in" | "out";

export type OperandType = "tag" | "number" | "time" | "unknown";

export interface Operand {
  /** Trimmed source text, printed back verbatim. */
  raw: string;
  type: OperandType;
  /** Numeric value for number (incl. radix) and time (ms) operands. */
  value?: number;
}

export interface Instr {
  kind: "instr";
  /** `r{rung ordinal}i{index}`, unique in a program. */
  id: string;
  mnemonic: Mnemonic;
  operands: Operand[];
  /** Position of the instruction in its rung, in text order (0-based). */
  index: number;
  /** 0-based code-point offset of the mnemonic inside the rung body text. */
  col: number;
}

export interface Branch {
  kind: "branch";
  legs: Seq[];
}

export interface Seq {
  kind: "seq";
  items: (Instr | Branch)[];
}

export interface Rung {
  number: number;
  comment: string | null;
  body: Seq;
  /** 1-based source line. */
  line: number;
  /** Canonical text of the rung (ends with `;`). */
  text: string;
}

export type ParseErrorCode =
  | "E_SYNTAX"
  | "E_UNBALANCED"
  | "E_UNKNOWN_MNEMONIC"
  | "E_ARITY"
  | "E_EMPTY_OPERAND"
  | "E_EMPTY_RUNG"
  | "E_LIMIT";

export interface ParseError {
  code: ParseErrorCode;
  message: string;
  /** 1-based line, 0 when not applicable. */
  line: number;
  /** 1-based column in code points, 0 when not applicable. */
  col: number;
}

export interface ParseResult {
  ok: boolean;
  rungs: Rung[];
  errors: ParseError[];
}

export type Program = ParseResult;
