import { useRef } from "react";
import { AlertCircle, FileText } from "lucide-react";
import { LIMITS, type ParseError } from "../../engine";
import { SAMPLES } from "../lib/samples";

interface Props {
  value: string;
  onChange: (text: string) => void;
  errors: ParseError[];
  onSubmit: () => void;
  onLoadSample: (id: string) => void;
  disabled?: boolean;
}

/** Offset of (line, col) in text; both 1-based, col counted in code points. */
function offsetOf(text: string, line: number, col: number): number {
  const lines = text.split("\n");
  let off = 0;
  for (let i = 0; i < Math.min(line - 1, lines.length); i++) off += lines[i].length + 1;
  const target = [...(lines[line - 1] ?? "")].slice(0, Math.max(0, col - 1)).join("");
  return off + target.length;
}

export function ProgramEditor({ value, onChange, errors, onSubmit, onLoadSample, disabled }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const tooLong = value.length > LIMITS.program_chars;

  const jumpTo = (e: ParseError) => {
    const ta = ref.current;
    if (!ta || e.line < 1) return;
    const start = offsetOf(value, e.line, Math.max(1, e.col));
    ta.focus();
    ta.setSelectionRange(start, Math.min(value.length, start + 1));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <label htmlFor="llt-editor" className="flex items-center gap-2 text-slate-300" style={{ fontSize: "0.85rem", fontWeight: 500 }}>
          <FileText size={15} className="text-cyan-400" aria-hidden />
          Ladder text
        </label>
        <select
          aria-label="Load an example program"
          value=""
          onChange={(e) => e.target.value && onLoadSample(e.target.value)}
          className="px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 focus:outline-none focus:border-cyan-500"
          style={{ fontSize: "0.75rem" }}
        >
          <option value="">Load an example…</option>
          {SAMPLES.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>
      <textarea
        id="llt-editor"
        ref={ref}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            onSubmit();
          }
        }}
        spellCheck={false}
        autoCapitalize="off"
        autoCorrect="off"
        aria-describedby="llt-help llt-errors"
        aria-invalid={errors.length > 0 || tooLong}
        placeholder={"// one rung per line, Rockwell neutral text or IEC aliases\nXIC(Start_PB)[XIC(Motor),]XIO(Stop_PB)OTE(Motor);"}
        className="w-full h-56 px-3 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-slate-200 placeholder-slate-600 focus:outline-none focus:border-cyan-500 resize-y"
        style={{ fontFamily: "'Fira Code', ui-monospace, monospace", fontSize: "0.78rem", lineHeight: 1.55, tabSize: 2 }}
      />
      <p id="llt-help" className="text-slate-500" style={{ fontSize: "0.72rem" }}>
        Paste rungs copied from Studio 5000 / RSLogix (neutral text) or type IEC aliases (NO, NC, COIL, SET, RESET).{" "}
        <kbd className="px-1 rounded bg-slate-800 border border-slate-700">Ctrl</kbd>+<kbd className="px-1 rounded bg-slate-800 border border-slate-700">Enter</kbd> analyses.
        <span className={tooLong ? "text-red-400 ml-2" : "ml-2"}>{value.length.toLocaleString()} / {LIMITS.program_chars.toLocaleString()} chars</span>
      </p>
      <div id="llt-errors" aria-live="polite">
        {errors.length > 0 && (
          <ul className="space-y-1 max-h-40 overflow-y-auto rounded-lg border border-red-500/25 bg-red-500/5 p-2">
            {errors.slice(0, 50).map((e, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => jumpTo(e)}
                  className="w-full text-left flex items-start gap-2 text-red-300 hover:text-red-200"
                  style={{ fontSize: "0.75rem" }}
                >
                  <AlertCircle size={13} className="mt-0.5 flex-shrink-0" aria-hidden />
                  <span>
                    {e.line > 0 ? `Line ${e.line}${e.col ? `, col ${e.col}` : ""}: ` : ""}
                    {e.message} <span className="text-red-400/60 font-mono">{e.code}</span>
                  </span>
                </button>
              </li>
            ))}
            {errors.length > 50 && <li className="text-red-400/70" style={{ fontSize: "0.72rem" }}>…and {errors.length - 50} more</li>}
          </ul>
        )}
      </div>
    </div>
  );
}
