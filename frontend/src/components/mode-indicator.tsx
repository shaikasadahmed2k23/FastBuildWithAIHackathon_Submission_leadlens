"use client";

import { type Health } from "@/lib/api";
import { useHealth } from "@/lib/use-health";
import { cn } from "@/lib/utils";

const PROVIDER_NAME: Record<string, string> = { groq: "Groq", gemini: "Gemini" };

export function describeMode(h: Health): { label: string; detail: string; tone: "green" | "amber" | "zinc" } {
  const provider = h.llm ? (PROVIDER_NAME[h.llm] ?? h.llm) : null;
  switch (h.llm_status) {
    case "ok":
      return { label: `LLM: ${provider}`, detail: `Last ${provider} call succeeded`, tone: "green" };
    case "untested":
      return { label: `LLM: ${provider}`, detail: `${provider} key configured; no call made yet`, tone: "zinc" };
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
  if (q.isError) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-700">
        <span className="size-1.5 rounded-full bg-red-500" /> API unreachable
      </span>
    );
  }
  if (!q.data) return null;
  const { label, detail, tone } = describeMode(q.data);
  return (
    <span
      title={detail}
      aria-label={`Mode: ${label}. ${detail}`}
      className="inline-flex items-center gap-1.5 rounded border border-zinc-200 bg-white px-2 py-0.5 text-xs text-zinc-700"
    >
      <span
        className={cn(
          "size-1.5 rounded-full",
          tone === "green" ? "bg-emerald-500" : tone === "amber" ? "bg-amber-500" : "bg-zinc-400",
        )}
      />
      {label}
    </span>
  );
}
