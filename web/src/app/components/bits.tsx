// Small shared UI pieces: severity badge, panel card, accessible tabs.

import { useRef, type ReactNode } from "react";
import type { Severity } from "../../engine";

export const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "text-red-300 bg-red-500/10 border-red-500/30",
  high: "text-orange-300 bg-orange-500/10 border-orange-500/30",
  medium: "text-amber-300 bg-amber-500/10 border-amber-500/30",
  low: "text-sky-300 bg-sky-500/10 border-sky-500/30",
};

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low"];

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded border uppercase ${SEVERITY_STYLE[severity]}`} style={{ fontSize: "0.62rem", fontWeight: 700, letterSpacing: "0.04em" }}>
      {severity}
    </span>
  );
}

export function Card({ title, icon, children, actions, className = "" }: { title?: ReactNode; icon?: ReactNode; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`p-4 rounded-xl bg-slate-900 border border-slate-700/80 ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-2 mb-3 flex-wrap">
          {title && (
            <h2 className="flex items-center gap-2 text-slate-200" style={{ fontSize: "0.9rem", fontWeight: 600 }}>
              {icon}
              {title}
            </h2>
          )}
          {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export interface TabDef<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
  badge?: number;
  disabled?: boolean;
}

/** WAI-ARIA tabs with arrow-key navigation. */
export function Tabs<T extends string>({ tabs, active, onChange, label, idPrefix }: { tabs: TabDef<T>[]; active: T; onChange: (id: T) => void; label: string; idPrefix: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const enabled = tabs.filter((t) => !t.disabled);
  const move = (dir: number) => {
    const i = enabled.findIndex((t) => t.id === active);
    const next = enabled[(i + dir + enabled.length) % enabled.length];
    if (!next) return;
    onChange(next.id);
    refs.current[tabs.indexOf(next)]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 pb-1">
      {tabs.map((t, i) => {
        const selected = t.id === active;
        return (
          <button
            key={t.id}
            ref={(el) => { refs.current[i] = el; }}
            role="tab"
            id={`${idPrefix}-tab-${t.id}`}
            aria-selected={selected}
            aria-controls={`${idPrefix}-panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight") { e.preventDefault(); move(1); }
              if (e.key === "ArrowLeft") { e.preventDefault(); move(-1); }
            }}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg whitespace-nowrap flex-shrink-0 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 ${
              selected ? "bg-slate-700 text-cyan-300 border border-slate-600" : t.disabled ? "text-slate-600 cursor-not-allowed" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800"
            }`}
            style={{ fontSize: "0.78rem" }}
          >
            {t.icon}
            {t.label}
            {t.badge ? (
              <span className="px-1.5 rounded-full bg-red-500/20 text-red-300" style={{ fontSize: "0.65rem" }}>{t.badge}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, idPrefix, active, children }: { id: string; idPrefix: string; active: boolean; children: ReactNode }) {
  if (!active) return null;
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-tab-${id}`} tabIndex={0} className="focus:outline-none">
      {children}
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  return (
    <button
      type="button"
      onClick={() => void navigator.clipboard?.writeText(text).catch(() => undefined)}
      className="px-2.5 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700"
      style={{ fontSize: "0.75rem" }}
    >
      {label}
    </button>
  );
}
