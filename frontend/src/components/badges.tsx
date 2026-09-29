import type { ActionStatus, IssueType, Stage } from "@/lib/api";
import { cn } from "@/lib/utils";

type Dot = "ink" | "muted" | "hollow" | "accent" | "alert" | "pending";

const DOT: Record<Dot, string> = {
  ink: "bg-ink-700",
  muted: "bg-ink-300",
  hollow: "border border-ink-500",
  accent: "bg-accent",
  alert: "bg-alert",
  pending: "bg-pending",
};

/** Small-caps text label with a coloured dot; the ledger's replacement for pill badges. */
export function DotLabel({ dot, children, className }: { dot: Dot; children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("smallcaps inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-ink-700", className)}>
      <span aria-hidden className={cn("size-[7px] shrink-0 rounded-full", DOT[dot])} />
      {children}
    </span>
  );
}

const STAGE_DOT: Record<Stage, Dot> = {
  new: "hollow",
  contacted: "muted",
  qualified: "muted",
  proposal: "ink",
  negotiation: "ink",
  won: "accent",
  lost: "hollow",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return (
    <DotLabel dot={STAGE_DOT[stage]} className={stage === "lost" ? "text-ink-500" : undefined}>
      {stage}
    </DotLabel>
  );
}

const ISSUE_LABEL: Record<IssueType, string> = { duplicate: "Duplicate", stale: "Stale", missing_field: "Missing field" };
// Vermilion is reserved for staleness (overdue follow-up); the other issues stay in ink.
const ISSUE_DOT: Record<IssueType, Dot> = { duplicate: "ink", stale: "alert", missing_field: "hollow" };

export function IssueBadge({ issue }: { issue: IssueType }) {
  return <DotLabel dot={ISSUE_DOT[issue]}>{ISSUE_LABEL[issue]}</DotLabel>;
}

export const issueLabel = (i: IssueType) => ISSUE_LABEL[i];

/** Pending reads as a dot label; decided actions get an outlined stamp. */
export function StatusBadge({ status }: { status: ActionStatus }) {
  if (status === "pending") return <DotLabel dot="pending">pending</DotLabel>;
  return (
    <span
      className={cn(
        "inline-flex items-center whitespace-nowrap rounded-sm border px-1.5 py-px font-mono text-[10px] font-medium uppercase leading-4 tracking-[0.14em]",
        status === "rejected" ? "border-ink-500 text-ink-600" : "border-accent text-accent",
      )}
    >
      {status}
    </span>
  );
}
