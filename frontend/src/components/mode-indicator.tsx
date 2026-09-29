"use client";

import { DotLabel } from "@/components/badges";
import { type Health } from "@/lib/api";
import { useHealth } from "@/lib/use-health";

const PROVIDER_NAME: Record<string, string> = { groq: "Groq", gemini: "Gemini" };

export function describeMode(h: Health): { label: string; detail: string; tone: "green" | "amber" | "neutral" } {
  const provider = h.llm ? (PROVIDER_NAME[h.llm] ?? h.llm) : null;
  switch (h.llm_status) {
    case "ok":
      return { label: `LLM: ${provider}`, detail: `Last ${provider} call succeeded`, tone: "green" };
    case "untested":
      return { label: `LLM: ${provider}`, detail: `${provider} key configured; no call made yet`, tone: "neutral" };
    case "failing":
      return {
        label: "Rule-based fallback",
        detail: `${provider} is configured but the last call failed${h.llm_last_call.error ? ` (${h.llm_last_call.error})` : ""}`,
        tone: "amber",
      };
    default:
      return { label: "Rule-based fallback", detail: "No LLM key configured", tone: "amber" };
  }
}

/** Always-visible indicator of which path answers questions right now. */
export function ModeIndicator() {
  const q = useHealth();
  if (q.isError) return <DotLabel dot="alert">API unreachable</DotLabel>;
  if (!q.data) return null;
  const { label, detail, tone } = describeMode(q.data);
  return (
    <span title={detail} aria-label={`Mode: ${label}. ${detail}`}>
      <DotLabel dot={tone === "green" ? "accent" : tone === "amber" ? "pending" : "hollow"}>{label}</DotLabel>
    </span>
  );
}
