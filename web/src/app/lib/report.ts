// Markdown report of an analysis. Every user-derived string (tag names, comments, program text)
// is escaped or fenced so a crafted tag cannot inject links, images or HTML into a viewer.

import type { Analysis } from "../../engine";
import { platformLabel } from "./platforms";

/** Escape Markdown/HTML-significant characters in inline text. */
export function mdEscape(text: string): string {
  return text
    .replace(/[\\`*_{}[\]()#+\-.!|<>~]/g, (c) => `\\${c}`)
    .replace(/\r?\n/g, " ");
}

/** A fenced code block whose fence is longer than any backtick run inside the content. */
export function mdFence(content: string, lang = ""): string {
  const longest = Math.max(0, ...[...content.matchAll(/`+/g)].map((m) => m[0].length));
  const fence = "`".repeat(Math.max(3, longest + 1));
  return `${fence}${lang}\n${content}\n${fence}`;
}

export interface ReportInput {
  name: string;
  platform: string;
  generatedAt: string;
  programText: string;
  analysis: Analysis;
  source: "text" | "image";
}

export function buildReport({ name, platform, generatedAt, programText, analysis, source }: ReportInput): string {
  const { faults, stats, corrections, st } = analysis;
  const out: string[] = [];
  out.push(`# LogicLens analysis: ${mdEscape(name)}`, "");
  out.push(`- Generated: ${mdEscape(generatedAt)}`);
  out.push(`- Platform: ${mdEscape(platformLabel(platform))}`);
  out.push(`- Source: ${source === "image" ? "image recognition (reviewed by the user)" : "ladder text"}`);
  out.push(`- Rungs: ${stats.rungs}, instructions: ${stats.instructions}, tags: ${stats.tags}, timers: ${stats.timers}, counters: ${stats.counters}`);
  out.push(`- Risk score: **${faults.riskScore}/100** (${mdEscape(faults.grade)})`);
  out.push(`- Findings: ${faults.counts.critical} critical, ${faults.counts.high} high, ${faults.counts.medium} medium, ${faults.counts.low} low`, "");
  out.push("> Advisory only. LogicLens output must be verified by a qualified control-systems engineer before any change to a live system. It is not a safety verification (IEC 61508 / IEC 61511).", "");

  out.push("## Findings", "");
  if (!faults.findings.length) out.push("No findings.", "");
  for (const f of faults.findings) {
    out.push(`### [${f.severity.toUpperCase()}] ${mdEscape(f.title)}`, "");
    out.push(`- Rule: \`${f.rule}\` (${f.basis === "rule" ? "deterministic rule" : "heuristic"}, confidence ${f.confidence}%)`);
    if (f.rungs.length) out.push(`- Rungs: ${f.rungs.join(", ")}`);
    if (f.tags.length) out.push(`- Tags: ${f.tags.map(mdEscape).join(", ")}`);
    if (f.standard) out.push(`- Reference: ${mdEscape(f.standard)}`);
    out.push("", mdEscape(f.description), "", `**Recommendation:** ${mdEscape(f.recommendation)}`, "");
  }

  out.push("## Checklist (LogicLens Prompt Playbook, 19 items)", "", "| Item | Result | Note |", "|---|---|---|");
  for (const [key, entry] of Object.entries(faults.checklist)) {
    out.push(`| ${key} | ${entry.status} | ${mdEscape(entry.reason ?? "")} |`);
  }
  out.push("");

  out.push("## Suggested corrections", "");
  if (!corrections.patches.length && !corrections.advisories.length) out.push("None.", "");
  for (const p of corrections.patches) {
    out.push(`### ${mdEscape(p.description)}${p.autoApplicable ? "" : " (needs your confirmation)"}`, "");
    out.push("Before:", "", mdFence(p.before.join("\n") || "(new rung)"), "", "After:", "", mdFence(p.after.join("\n") || "(rung removed)"), "");
    if (p.verification.length) out.push("Verify:", "", ...p.verification.map((v) => `1. ${mdEscape(v)}`), "");
  }
  for (const a of corrections.advisories) out.push(`- ${mdEscape(a.note)}`);
  out.push("");

  out.push("## Structured Text (IEC 61131-3)", "", mdFence(st.code, "iecst"), "");
  if (st.warnings.length) out.push("Translation notes:", "", ...st.warnings.map((w) => `- ${mdEscape(w)}`), "");
  out.push("## Program (LogicLens Ladder Text)", "", mdFence(programText), "");
  return out.join("\n");
}
