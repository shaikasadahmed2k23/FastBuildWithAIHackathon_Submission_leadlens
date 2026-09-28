import { Badge } from "@/components/ui/badge";
import type { ActionStatus, IssueType, Stage } from "@/lib/api";

const STAGE_TONE: Record<Stage, "neutral" | "green" | "red" | "blue"> = {
  new: "neutral",
  contacted: "neutral",
  qualified: "neutral",
  proposal: "blue",
  negotiation: "blue",
  won: "green",
  lost: "red",
};

export function StageBadge({ stage }: { stage: Stage }) {
  return <Badge tone={STAGE_TONE[stage]}>{stage}</Badge>;
}

const ISSUE_LABEL: Record<IssueType, string> = { duplicate: "Duplicate", stale: "Stale", missing_field: "Missing field" };
const ISSUE_TONE: Record<IssueType, "amber" | "red"> = { duplicate: "red", stale: "amber", missing_field: "amber" };

export function IssueBadge({ issue }: { issue: IssueType }) {
  return <Badge tone={ISSUE_TONE[issue]}>{ISSUE_LABEL[issue]}</Badge>;
}

export const issueLabel = (i: IssueType) => ISSUE_LABEL[i];

const STATUS_TONE: Record<ActionStatus, "neutral" | "green" | "red" | "amber" | "blue"> = {
  pending: "amber",
  approved: "blue",
  executed: "green",
  rejected: "neutral",
};

export function StatusBadge({ status }: { status: ActionStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>;
}
