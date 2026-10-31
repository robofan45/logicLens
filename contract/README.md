# LogicLens contract v1.0

Everything that crosses a boundary between `web/`, `backend/` and `ml/` is defined here.
Both ladder parsers (TypeScript in `web/src/engine/parse.ts`, Python in
`contract/python/logiclens_ladder.py`) must pass `ladder_cases.json` unchanged.
If you change the grammar, change it here first, add a case, then update both parsers.

## 1. LogicLens Ladder Text (LLT)

A strict, documented subset of Rockwell "neutral text" (what Studio 5000 / RSLogix put on the
clipboard when you copy a rung as text), plus IEC 61131-3 aliases.

```
XIC(Start_PB)[XIC(Motor_Run),XIC(Remote_Start)]XIO(Stop_PB)OTE(Motor_Run);
```

### 1.1 Lines, rungs and comments

1. Text is split into lines (`\n` or `\r\n`).
2. `//` outside parentheses starts a comment that runs to the end of the line.
3. A line whose first non-blank characters are `#` is a whole-line comment.
4. Comment lines with no code accumulate (joined with `\n`) and attach to the **next** rung.
   An inline comment after code attaches to the **last** rung on that line (appended after any
   pending comment, joined with `\n`).
5. Optional rung label at the start of the code: `0003:`, `Rung 3:`, `Network 3:`, `N 3:` with `:`
   `.` or `)` after the number (case-insensitive), or a bare `N:` (L5K export). A numbered label sets
   that rung's number; otherwise numbers continue from the previous rung (+1), starting at 0.
6. `;` outside parentheses ends a rung. Several rungs may share a line. A final `;` is optional.
7. Blank lines are ignored.

### 1.2 Rung body grammar

```
rung    := seq                         (must contain at least one instruction)
seq     := elem*
elem    := instr | branch
branch  := '[' seq (',' seq)* ']'      (an empty leg is a plain wire = always passes power)
instr   := MNEMONIC '(' [operand (',' operand)*] ')'
```

* Whitespace outside operands is insignificant. Mnemonics are case-insensitive and printed upper-case.
* An operand is the trimmed text between separators. It may contain balanced `()` / `[]`
  (array indexes such as `Data[3]`). Empty operands are errors.
* Operand types: `unknown` (`?`, Rockwell's unassigned marker), `number` (decimal, `-1.5`, `2e3`,
  `16#FF`), `time` (IEC literal `T#5s`, `T#1m30s`, `TIME#250ms`, units d h m s ms, value in ms),
  otherwise `tag` (`I:1/0`, `B3:0/1`, `T4:0.DN`, `%I0.0`, `Local:1:I.Data.0`, `#Start`, `Motor.Run`).
* Tags compare case-insensitively (`motor_run` == `Motor_Run`); the first spelling seen is displayed.

### 1.3 Instructions (canonical mnemonic, arity, role)

| Canonical | Aliases | Operands | Role |
|---|---|---|---|
| XIC | NO | bit | input: passes power when bit = 1 |
| XIO | NC | bit | input: passes power when bit = 0 |
| ONS | | storage | input: passes power on the scan the rung goes 0 to 1 |
| P | | bit | input (IEC): passes power on rising edge of bit |
| N | | bit | input (IEC): passes power on falling edge of bit |
| EQU NEQ GRT GEQ LES LEQ | | a, b | input: compare |
| LIM | | low, test, high | input: low <= test <= high (circular when low > high) |
| AFI | | (none) | input: always false |
| LBL | | label | input: jump target, always passes power |
| OTE | COIL, OUT | bit | output: bit := rung condition |
| OTL | SET, S | bit | output: latch to 1 when condition is 1 |
| OTU | RESET, R | bit | output: unlatch to 0 when condition is 1 |
| NCOIL | | bit | output (IEC negated coil): bit := NOT condition |
| OSR OSF | | storage, output | output: output bit = one-scan pulse on rising / falling condition |
| TON TOF RTO | | timer, preset[, accum] **or** timer, base, preset, accum (SLC) | output: timers |
| TP | | timer, preset[, accum] | output (IEC pulse timer) |
| CTU CTD | | counter, preset[, accum] | output: count on rising condition |
| CTUD | | counter, preset[, down_input_bit] | output (IEC): up on rising condition, down on rising `down_input_bit` |
| RES | | timer_or_counter | output: reset ACC/DN |
| ADD SUB MUL DIV AND OR XOR | | a, b, dest | output: dest := a op b when condition is 1 |
| MOV NOT | | source, dest | output: dest := source / bitwise NOT |
| JMP | | label | output: jump forward to LBL |
| JSR | | routine[, params...] (max 8) | output: call subroutine (not modelled, warning) |
| MCR | | (none) | output: master control zone start (with conditions) / end (unconditional) |
| END | | (none) | output: end of program |
| NOP | | (none) | output: no operation |

Timer preset in milliseconds: Logix `TON(T,5000,0)` = 5000 ms; SLC `TON(T4:0,0.01,500,0)` =
base s x preset = 5000 ms; IEC `TON(T1,T#5s)` = 5000 ms. A tag preset is resolved at run time.
Timer/counter sub-elements: `.DN .TT .EN .ACC .PRE .CU .CD` and IEC `.Q` (= DN), `.ET` (= ACC), `.CV` (= ACC), `.PV` (= PRE).

### 1.4 Evaluation semantics (Logix rung-condition model)

Power flows left to right. Every instruction receives *rung-condition-in*; an input instruction
returns `in AND test`; an output instruction acts on `in` and passes it through unchanged (so
outputs may sit in series, in branch legs, or mid-rung). A branch gives each leg the same `in`
and returns the OR of the legs. Rungs execute top to bottom and writes are visible to later rungs
in the same scan. Inputs are sampled once per scan.

### 1.5 Limits (enforced by both parsers, part of the security model)

| Limit | Value |
|---|---|
| program text | 200 000 characters |
| rungs | 2 000 |
| rung text | 4 000 characters |
| instructions per rung | 256 |
| branch nesting depth | 16 |
| operands per instruction | 8 |
| operand length | 120 characters |

### 1.6 Errors

Parsers never throw on bad input. They return every valid rung plus a list of
`{code, message, line, col}` where `code` is one of
`E_SYNTAX`, `E_UNBALANCED`, `E_UNKNOWN_MNEMONIC`, `E_ARITY`, `E_EMPTY_OPERAND`, `E_EMPTY_RUNG`, `E_LIMIT`.
`line` is 1-based; `col` is 1-based within that line (0 when not applicable).

### 1.7 Canonical text

Upper-case mnemonics, no spaces outside operands, operands joined with `,`, branches as
`[leg,leg]`, every rung ends with `;`. A program prints each rung's comment lines as `// text`
before the rung. Labels are not printed. `parse(print(parse(x)))` must equal `parse(x)`.

## 2. Program JSON (backend `POST /api/analyze/parse` -> web)

See `program.schema.json`. The web app treats `rungs[].text` as authoritative and re-parses it;
`rungs[].elements[i]` is aligned with the *i*-th instruction of that rung in text order and only
carries overlay data (box, confidence). Boxes are `[x1, y1, x2, y2]` in source-image pixels.

## 3. Detector classes

`classes.json` keeps the 44 legacy class IDs from `generate_plc_dataset.py` so old labels stay
readable. `mnemonic` maps a symbol class to its LLT instruction; structural classes have `null`.
v2 labels never emit `Horizontal_Wire` (38) or `Vertical_Wire` (39); branch connectors are
labelled `Branch_Start` (40, left vertical) and `Branch_End` (41, right vertical).

## 4. Explain / chat (backend -> web)

`POST /api/analyze/explain` body `{program_text, platform?, user_context?, findings?}` returns
`{summary, rung_explanations:[{rung, text}], ai_findings:[{severity, title, rungs, description,
recommendation}], model, disclaimer}`. `POST /api/chat` body `{program_text, question, history?}`
returns `{answer, model, disclaimer}`. Both answer 503 `E_LLM_DISABLED` when no LLM is configured.

## 5. Error envelope (all backend errors)

`{"error": {"code": "E_...", "message": "human readable", "request_id": "...", "details": [...]?}}`

`details` is optional (for example the parser errors behind a 422 `E_LADDER_SYNTAX`).

## 6. Synthetic rendering conventions (dataset v2 <-> backend assembler)

These are what `ml/` renders and what `backend/app/engines/assembler.py` assumes. Real
screenshots (see `samples/ladder_logic_program_PLC1.webp`, RSLogix 500 style) follow the same
visual grammar, which is why the conventions copy it.

1. A diagram has a left and a right power rail (full-height vertical lines). Rungs are horizontal
   lines between the rails, top to bottom, with the rung number printed left of the left rail.
2. A symbol box (YOLO label) is tight around the symbol graphic only: contact brackets `] [`
   (`]/[` for XIO, `]P[`/`]N[` for edges), coil parentheses `( )` (`(L)`, `(U)`, `(/)`), or the
   rectangle of a box instruction (TON, CTU, MOV, compare, math...). Tag text is **not** inside
   the box of a contact or coil.
3. Contact and coil operands are printed centred above the symbol. In RSLogix 500 style the
   address may be split: file part above (`I:1`) and bit number below (`1`) -> `I:1/1`.
4. Box instructions print their mnemonic in the top row of the rectangle and their operands on
   the following rows inside it (`Timer T4:0`, `Preset 500`, `Accum 0`, `Source A Level`...).
5. Series instructions on a rung sit on the rung line, left to right, in text order. Output
   instructions are drawn right-aligned against the right rail; several outputs on one rung are
   drawn as a parallel output branch.
6. A parallel branch draws its first leg on the rung line and each further leg on its own row
   below, joined by a vertical connector at each end. Label the left connector `Branch_Start` (40)
   and the right connector `Branch_End` (41); connector boxes are at least 6 px wide.
7. Rails are labelled `Power_Rail_Left` (42) / `Power_Rail_Right` (43). Wires (38, 39) are never
   labelled.
