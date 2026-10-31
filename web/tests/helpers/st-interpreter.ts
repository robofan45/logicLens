// A small interpreter for exactly the Structured Text subset that src/engine/st.ts emits.
// Used by the differential tests: the ladder simulator and this interpreter must agree
// output-by-output, scan-by-scan. FB semantics mirror src/engine/simulate.ts (the enabling
// call of a timer contributes 0 ms; every later call adds dt).

type Value = boolean | number;

interface Tok {
  t: "id" | "num" | "time" | "op" | "eof";
  v: string;
  n?: number;
}

function toDint(v: number): number {
  return Number.isFinite(v) ? Math.trunc(v) | 0 : 0;
}

const UNIT: Record<string, number> = { d: 86_400_000, h: 3_600_000, m: 60_000, s: 1000, ms: 1 };

function lex(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i++;
      continue;
    }
    if (src.startsWith("(*", i)) {
      const end = src.indexOf("*)", i + 2);
      if (end < 0) throw new Error("unterminated comment");
      i = end + 2;
      continue;
    }
    const time = /^(?:T|TIME)#(-?)((?:\d+(?:\.\d+)?(?:ms|d|h|m|s))+)/i.exec(src.slice(i));
    if (time) {
      let ms = 0;
      for (const p of time[2].matchAll(/(\d+(?:\.\d+)?)(ms|d|h|m|s)/gi)) ms += Number(p[1]) * UNIT[p[2].toLowerCase()];
      out.push({ t: "time", v: time[0], n: time[1] ? -ms : ms });
      i += time[0].length;
      continue;
    }
    const radix = /^(2|8|16)#([0-9A-Fa-f_]+)/.exec(src.slice(i));
    if (radix) {
      out.push({ t: "num", v: radix[0], n: parseInt(radix[2].replace(/_/g, ""), Number(radix[1])) });
      i += radix[0].length;
      continue;
    }
    const num = /^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(src.slice(i));
    if (num) {
      out.push({ t: "num", v: num[0], n: Number(num[0]) });
      i += num[0].length;
      continue;
    }
    const id = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i));
    if (id) {
      out.push({ t: "id", v: id[0].toUpperCase() });
      i += id[0].length;
      continue;
    }
    const op = /^(:=|<=|>=|<>|[=<>+\-*/(),;:.])/.exec(src.slice(i));
    if (op) {
      out.push({ t: "op", v: op[0] });
      i += op[0].length;
      continue;
    }
    throw new Error(`unexpected '${c}' at ${i}`);
  }
  out.push({ t: "eof", v: "" });
  return out;
}

type Expr =
  | { k: "lit"; v: Value }
  | { k: "var"; name: string; field?: string }
  | { k: "un"; op: string; a: Expr }
  | { k: "bin"; op: string; a: Expr; b: Expr }
  | { k: "call"; fn: string; a: Expr };

type Stmt =
  | { k: "assign"; name: string; e: Expr }
  | { k: "if"; arms: { c: Expr; body: Stmt[] }[]; otherwise: Stmt[] }
  | { k: "fb"; name: string; args: [string, Expr][] };

const FB_TYPES = new Set(["TON", "TOF", "TP", "TONR", "CTU", "CTUD", "R_TRIG", "F_TRIG"]);

class Parser {
  i = 0;
  constructor(private readonly toks: Tok[]) {}
  peek(o = 0) {
    return this.toks[this.i + o];
  }
  next() {
    return this.toks[this.i++];
  }
  isOp(v: string) {
    return this.peek().t === "op" && this.peek().v === v;
  }
  isId(v: string) {
    return this.peek().t === "id" && this.peek().v === v;
  }
  expectOp(v: string) {
    const t = this.next();
    if (t.t !== "op" || t.v !== v) throw new Error(`expected '${v}', got '${t.v}' at token ${this.i}`);
  }
  expectId(v?: string) {
    const t = this.next();
    if (t.t !== "id" || (v && t.v !== v)) throw new Error(`expected ${v ?? "identifier"}, got '${t.v}' at token ${this.i}`);
    return t.v;
  }

  program(): { decls: [string, string][]; body: Stmt[] } {
    this.expectId("PROGRAM");
    this.expectId();
    this.expectId("VAR");
    const decls: [string, string][] = [];
    while (!this.isId("END_VAR")) {
      const name = this.expectId();
      this.expectOp(":");
      const type = this.expectId();
      this.expectOp(";");
      decls.push([name, type]);
    }
    this.expectId("END_VAR");
    const body = this.stmts(["END_PROGRAM"]);
    this.expectId("END_PROGRAM");
    return { decls, body };
  }

  stmts(stop: string[]): Stmt[] {
    const out: Stmt[] = [];
    while (!(this.peek().t === "id" && stop.includes(this.peek().v))) {
      if (this.peek().t === "eof") throw new Error("unexpected end of program");
      if (this.isOp(";")) {
        this.next();
        continue;
      }
      if (this.isId("IF")) {
        this.next();
        const arms: { c: Expr; body: Stmt[] }[] = [];
        const c = this.expr();
        this.expectId("THEN");
        arms.push({ c, body: this.stmts(["ELSIF", "ELSE", "END_IF"]) });
        let otherwise: Stmt[] = [];
        while (this.isId("ELSIF")) {
          this.next();
          const c2 = this.expr();
          this.expectId("THEN");
          arms.push({ c: c2, body: this.stmts(["ELSIF", "ELSE", "END_IF"]) });
        }
        if (this.isId("ELSE")) {
          this.next();
          otherwise = this.stmts(["END_IF"]);
        }
        this.expectId("END_IF");
        this.expectOp(";");
        out.push({ k: "if", arms, otherwise });
        continue;
      }
      const name = this.expectId();
      if (this.isOp(":=")) {
        this.next();
        const e = this.expr();
        this.expectOp(";");
        out.push({ k: "assign", name, e });
        continue;
      }
      this.expectOp("(");
      const args: [string, Expr][] = [];
      while (!this.isOp(")")) {
        const p = this.expectId();
        this.expectOp(":=");
        args.push([p, this.expr()]);
        if (this.isOp(",")) this.next();
      }
      this.expectOp(")");
      this.expectOp(";");
      out.push({ k: "fb", name, args });
    }
    return out;
  }

  expr(): Expr {
    let a = this.xor();
    while (this.isId("OR")) {
      this.next();
      a = { k: "bin", op: "OR", a, b: this.xor() };
    }
    return a;
  }
  xor(): Expr {
    let a = this.and();
    while (this.isId("XOR")) {
      this.next();
      a = { k: "bin", op: "XOR", a, b: this.and() };
    }
    return a;
  }
  and(): Expr {
    let a = this.eq();
    while (this.isId("AND")) {
      this.next();
      a = { k: "bin", op: "AND", a, b: this.eq() };
    }
    return a;
  }
  eq(): Expr {
    let a = this.rel();
    while (this.isOp("=") || this.isOp("<>")) {
      const op = this.next().v;
      a = { k: "bin", op, a, b: this.rel() };
    }
    return a;
  }
  rel(): Expr {
    let a = this.add();
    while (this.isOp("<") || this.isOp(">") || this.isOp("<=") || this.isOp(">=")) {
      const op = this.next().v;
      a = { k: "bin", op, a, b: this.add() };
    }
    return a;
  }
  add(): Expr {
    let a = this.mul();
    while (this.isOp("+") || this.isOp("-")) {
      const op = this.next().v;
      a = { k: "bin", op, a, b: this.mul() };
    }
    return a;
  }
  mul(): Expr {
    let a = this.unary();
    while (this.isOp("*") || this.isOp("/") || this.isId("MOD")) {
      const op = this.next().v;
      a = { k: "bin", op, a, b: this.unary() };
    }
    return a;
  }
  unary(): Expr {
    if (this.isId("NOT")) {
      this.next();
      return { k: "un", op: "NOT", a: this.unary() };
    }
    if (this.isOp("-")) {
      this.next();
      return { k: "un", op: "-", a: this.unary() };
    }
    return this.primary();
  }
  primary(): Expr {
    const t = this.next();
    if (t.t === "num" || t.t === "time") return { k: "lit", v: t.n! };
    if (t.t === "op" && t.v === "(") {
      const e = this.expr();
      this.expectOp(")");
      return e;
    }
    if (t.t === "id") {
      if (t.v === "TRUE") return { k: "lit", v: true };
      if (t.v === "FALSE") return { k: "lit", v: false };
      if (this.isOp("(")) {
        this.next();
        const a = this.expr();
        this.expectOp(")");
        return { k: "call", fn: t.v, a };
      }
      if (this.isOp(".")) {
        this.next();
        return { k: "var", name: t.v, field: this.expectId() };
      }
      return { k: "var", name: t.v };
    }
    throw new Error(`unexpected token '${t.v}'`);
  }
}

type FB = { __type: string } & Record<string, Value | string>;

export class StInterpreter {
  private readonly vars = new Map<string, Value>();
  private readonly types = new Map<string, string>();
  private readonly fbs = new Map<string, FB>();
  private readonly body: Stmt[];
  private dt = 0;

  constructor(code: string) {
    const prog = new Parser(lex(code)).program();
    for (const [name, type] of prog.decls) {
      if (this.types.has(name)) throw new Error(`duplicate declaration ${name}`);
      this.types.set(name, type);
      if (FB_TYPES.has(type)) this.fbs.set(name, this.newFb(type));
      else if (type === "BOOL") this.vars.set(name, false);
      else if (type === "DINT" || type === "REAL") this.vars.set(name, 0);
      else throw new Error(`unknown type ${type}`);
    }
    this.body = prog.body;
  }

  private newFb(type: string): FB {
    return { __type: type, IN: false, PT: 0, Q: false, ET: 0, R: false, CU: false, CD: false, PV: 0, CV: 0, QU: false, QD: false, CLK: false, M: false };
  }

  get(name: string): Value {
    const n = name.toUpperCase();
    if (!this.vars.has(n)) throw new Error(`no variable ${name}`);
    return this.vars.get(n)!;
  }

  set(name: string, v: Value): void {
    this.assign(name.toUpperCase(), v);
  }

  fb(name: string): FB | undefined {
    return this.fbs.get(name.toUpperCase());
  }

  scan(dtMs: number): void {
    this.dt = dtMs;
    this.run(this.body);
  }

  private assign(name: string, v: Value): void {
    const type = this.types.get(name);
    if (!type) throw new Error(`assignment to undeclared ${name}`);
    if (type === "BOOL") {
      if (typeof v !== "boolean") throw new Error(`type error: ${name} := ${v}`);
      this.vars.set(name, v);
    } else if (type === "DINT") {
      if (typeof v !== "number") throw new Error(`type error: ${name} := ${v}`);
      this.vars.set(name, toDint(v));
    } else if (type === "REAL") {
      if (typeof v !== "number") throw new Error(`type error: ${name} := ${v}`);
      this.vars.set(name, v);
    } else throw new Error(`cannot assign to FB ${name}`);
  }

  private run(stmts: Stmt[]): void {
    for (const s of stmts) {
      if (s.k === "assign") this.assign(s.name, this.eval(s.e));
      else if (s.k === "if") {
        const arm = s.arms.find((a) => this.bool(this.eval(a.c)));
        this.run(arm ? arm.body : s.otherwise);
      } else this.call(s.name, s.args);
    }
  }

  private bool(v: Value): boolean {
    if (typeof v !== "boolean") throw new Error(`type error: condition is ${v}`);
    return v;
  }

  private call(name: string, args: [string, Expr][]): void {
    const fb = this.fbs.get(name);
    if (!fb) throw new Error(`call of non-FB ${name}`);
    const a: Record<string, Value> = {};
    for (const [p, e] of args) a[p] = this.eval(e);
    const dt = this.dt;
    const step = (et: number, pt: number) => (pt <= 0 ? et : Math.min(et + dt, pt));
    switch (fb.__type) {
      case "TON": {
        const IN = a.IN as boolean;
        const PT = a.PT as number;
        if (IN) {
          fb.ET = fb.IN ? step(fb.ET as number, PT) : 0;
          fb.Q = (fb.ET as number) >= PT;
        } else {
          fb.ET = 0;
          fb.Q = false;
        }
        fb.IN = IN;
        fb.PT = PT;
        break;
      }
      case "TOF": {
        const IN = a.IN as boolean;
        const PT = a.PT as number;
        if (IN) {
          fb.Q = true;
          fb.ET = 0;
        } else {
          if (fb.IN) fb.ET = 0;
          else if (fb.Q) fb.ET = step(fb.ET as number, PT);
          if (fb.Q && (fb.ET as number) >= PT) fb.Q = false;
        }
        fb.IN = IN;
        fb.PT = PT;
        break;
      }
      case "TP": {
        const IN = a.IN as boolean;
        const PT = a.PT as number;
        const rising = IN && !fb.IN;
        if (fb.Q) {
          fb.ET = step(fb.ET as number, PT);
          if ((fb.ET as number) >= PT) fb.Q = false;
        } else if (rising && fb.ET === 0) {
          fb.Q = PT > 0;
          fb.ET = 0;
        }
        if (!fb.Q && !IN) fb.ET = 0;
        fb.IN = IN;
        fb.PT = PT;
        break;
      }
      case "TONR": {
        const IN = a.IN as boolean;
        const PT = a.PT as number;
        if (a.R) {
          fb.ET = 0;
          fb.Q = false;
        }
        if (IN && fb.IN && (fb.ET as number) < PT) fb.ET = step(fb.ET as number, PT);
        fb.Q = (fb.ET as number) >= PT;
        fb.IN = IN;
        fb.PT = PT;
        break;
      }
      case "CTU": {
        const CU = a.CU as boolean;
        const PV = a.PV as number;
        if (a.R) fb.CV = 0;
        else if (CU && !fb.CU) fb.CV = toDint((fb.CV as number) + 1);
        fb.CU = CU;
        fb.PV = PV;
        fb.Q = (fb.CV as number) >= PV;
        break;
      }
      case "CTUD": {
        const CU = (a.CU ?? false) as boolean;
        const CD = (a.CD ?? false) as boolean;
        const PV = a.PV as number;
        if (a.R) fb.CV = 0;
        else {
          const up = CU && !fb.CU;
          const dn = CD && !fb.CD;
          if (up && !dn) fb.CV = toDint((fb.CV as number) + 1);
          else if (dn && !up) fb.CV = toDint((fb.CV as number) - 1);
        }
        fb.CU = CU;
        fb.CD = CD;
        fb.PV = PV;
        fb.QU = (fb.CV as number) >= PV;
        fb.QD = (fb.CV as number) <= 0;
        break;
      }
      case "R_TRIG": {
        const CLK = a.CLK as boolean;
        fb.Q = CLK && !fb.M;
        fb.M = CLK;
        fb.CLK = CLK;
        break;
      }
      case "F_TRIG": {
        const CLK = a.CLK as boolean;
        fb.Q = !CLK && (fb.M as boolean);
        fb.M = CLK;
        fb.CLK = CLK;
        break;
      }
      default:
        throw new Error(`unknown FB type ${fb.__type}`);
    }
  }

  private eval(e: Expr): Value {
    switch (e.k) {
      case "lit":
        return e.v;
      case "var": {
        if (e.field) {
          const fb = this.fbs.get(e.name);
          if (!fb) throw new Error(`member access on non-FB ${e.name}`);
          if (!(e.field in fb) || e.field === "__type") throw new Error(`unknown member ${e.name}.${e.field}`);
          return fb[e.field] as Value;
        }
        if (!this.vars.has(e.name)) throw new Error(`undeclared ${e.name}`);
        return this.vars.get(e.name)!;
      }
      case "un": {
        const v = this.eval(e.a);
        if (e.op === "NOT") return typeof v === "boolean" ? !v : ~toDint(v);
        if (typeof v !== "number") throw new Error("unary minus on BOOL");
        return -v;
      }
      case "call": {
        const v = this.eval(e.a);
        switch (e.fn) {
          case "BOOL_TO_DINT":
            if (typeof v !== "boolean") throw new Error("BOOL_TO_DINT of non-BOOL");
            return v ? 1 : 0;
          case "TRUNC":
            return toDint(v as number);
          case "DINT_TO_REAL":
          case "TIME_TO_DINT":
          case "DINT_TO_TIME":
            if (typeof v !== "number") throw new Error(`${e.fn} of BOOL`);
            return v;
          default:
            throw new Error(`unknown function ${e.fn}`);
        }
      }
      case "bin": {
        const a = this.eval(e.a);
        const b = this.eval(e.b);
        switch (e.op) {
          case "AND":
          case "OR":
          case "XOR":
            if (typeof a === "boolean" && typeof b === "boolean") {
              return e.op === "AND" ? a && b : e.op === "OR" ? a || b : a !== b;
            }
            if (typeof a === "number" && typeof b === "number") {
              const x = toDint(a);
              const y = toDint(b);
              return e.op === "AND" ? x & y : e.op === "OR" ? x | y : x ^ y;
            }
            throw new Error(`mixed ${e.op}`);
          case "=":
            return a === b;
          case "<>":
            return a !== b;
          default:
            break;
        }
        if (typeof a !== "number" || typeof b !== "number") throw new Error(`arithmetic on BOOL (${e.op})`);
        switch (e.op) {
          case "<":
            return a < b;
          case ">":
            return a > b;
          case "<=":
            return a <= b;
          case ">=":
            return a >= b;
          case "+":
            return a + b;
          case "-":
            return a - b;
          case "*":
            return a * b;
          case "/":
            if (b === 0) throw new Error("division by zero reached at runtime");
            return a / b;
          default:
            throw new Error(`unknown operator ${e.op}`);
        }
      }
    }
  }
}
