"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import * as React from "react";

import { StatusBadge } from "@/components/badges";
import { CitationChip } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState } from "@/components/states";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { type Action, type ActionStatus, api } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

const TABS: { key: ActionStatus | "all"; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "executed", label: "Executed" },
  { key: "rejected", label: "Rejected" },
  { key: "all", label: "All" },
];
const TYPE_LABEL: Record<Action["type"], string> = { outreach: "Outreach", merge: "Merge duplicates", stage_change: "Stage change" };
const REVIEWER_KEY = "leadlens.reviewer";

function useReviewer() {
  const [name, setName] = React.useState("reviewer");
  React.useEffect(() => {
    try {
      const saved = localStorage.getItem(REVIEWER_KEY);
      if (saved) setName(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);
  const update = (v: string) => {
    setName(v);
    try {
      localStorage.setItem(REVIEWER_KEY, v);
    } catch {
      /* storage unavailable */
    }
  };
  return [name, update] as const;
}

export default function ApprovalsPage() {
  const [tab, setTab] = React.useState<ActionStatus | "all">("pending");
  const [reviewer, setReviewer] = useReviewer();
  const all = useQuery({ queryKey: ["actions", "all"], queryFn: () => api.actions() });
  const counts = React.useMemo(() => {
    const c: Record<string, number> = { all: all.data?.length ?? 0 };
    for (const a of all.data ?? []) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [all.data]);
  const items = (all.data ?? []).filter((a) => tab === "all" || a.status === tab);

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Every change to CRM data waits here for a human decision"
        actions={
          <label className="flex items-center gap-2 text-xs text-ink-500">
            Reviewing as
            <Input value={reviewer} onChange={(e) => setReviewer(e.target.value)} className="h-7 w-36 text-xs" maxLength={80} />
          </label>
        }
      />
      <div className="flex gap-4 border-b border-ink-200 px-6">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "-mb-px flex h-10 items-center gap-1.5 border-b-2 text-sm",
              tab === t.key ? "border-ink-900 text-ink-900" : "border-transparent text-ink-500 hover:text-ink-900",
            )}
          >
            {t.label}
            <span className="tnum font-mono text-2xs text-ink-400">{counts[t.key] ?? 0}</span>
          </button>
        ))}
      </div>
      <div className="mx-auto max-w-4xl space-y-3 p-6">
        {all.isLoading ? (
          Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-40" />)
        ) : all.isError ? (
          <ErrorState error={all.error} onRetry={() => all.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={tab === "pending" ? "Nothing waiting for review" : `No ${tab === "all" ? "" : tab} actions yet`}
            hint="Open a lead and propose an outreach, a merge or a stage change. It will appear here for approval."
          />
        ) : (
          items.map((a) => <ActionCard key={a.action_id} action={a} reviewer={reviewer} />)
        )}
      </div>
    </>
  );
}

function ActionCard({ action: a, reviewer }: { action: Action; reviewer: string }) {
  const [note, setNote] = React.useState("");
  const toast = useToast();
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (d: "approve" | "reject") => api.decide(a.action_id, d, { actor: reviewer.trim() || "reviewer", note: note || undefined }),
    onSuccess: (res) => {
      toast(
        res.status === "executed"
          ? `${res.action_id} approved and executed`
          : res.status === "approved"
            ? `${res.action_id} approved, but execution failed. See audit log.`
            : `${res.action_id} rejected`,
        res.status === "approved" ? "error" : "default",
      );
      for (const key of [["actions"], ["overview"], ["leads"], ["lead"], ["explain"]]) qc.invalidateQueries({ queryKey: key });
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Decision failed", "error"),
  });

  return (
    <article className="rounded border border-ink-200 bg-panel">
      <header className="flex items-center gap-2 border-b border-ink-200 px-4 py-2.5">
        <span className="text-sm font-medium">{TYPE_LABEL[a.type]}</span>
        <span className="font-mono text-2xs text-ink-500">{a.action_id}</span>
        <StatusBadge status={a.status} />
        <span className="tnum ml-auto text-2xs text-ink-500">Proposed {fmt.dateTime(a.created_at)}</span>
      </header>

      <div className="space-y-3 px-4 py-3 text-sm">
        <Payload action={a} />
        {a.note ? <p className="text-xs text-ink-500">Note: {a.note}</p> : null}
      </div>

      {a.status === "pending" ? (
        <div className="flex items-center gap-2 border-t border-ink-200 bg-ink-50/60 px-4 py-2.5">
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note for the audit log"
            className="h-7 text-xs"
            maxLength={500}
          />
          <Button size="sm" variant="danger" disabled={decide.isPending} onClick={() => decide.mutate("reject")}>
            Reject
          </Button>
          <Button size="sm" variant="primary" disabled={decide.isPending} onClick={() => decide.mutate("approve")}>
            Approve
          </Button>
        </div>
      ) : null}

      {a.audit.length ? (
        <ol className="space-y-1 border-t border-ink-200 px-4 py-2.5">
          {a.audit.map((e) => (
            <li key={e.id} className="flex gap-3 text-2xs">
              <span className="tnum w-28 shrink-0 text-ink-400">{fmt.dateTime(e.at)}</span>
              <span className="w-20 shrink-0 truncate text-ink-500">{e.actor}</span>
              <span className="text-ink-700">{e.event}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}

function Payload({ action: a }: { action: Action }) {
  if (a.type === "merge") {
    const primary = String(a.payload.primary_id);
    const others = a.lead_ids.filter((l) => l !== primary);
    return (
      <div className="flex flex-wrap items-center gap-2">
        {others.map((id) => (
          <CitationChip key={id} id={id} />
        ))}
        <ArrowRight className="size-3.5 text-ink-400" />
        <CitationChip id={primary} />
        <span className="text-xs text-ink-500">Activities move to the primary record; blank fields are filled from the duplicate.</span>
      </div>
    );
  }
  if (a.type === "stage_change") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        {a.lead_ids.map((id) => (
          <CitationChip key={id} id={id} />
        ))}
        <span className="text-ink-500">move to</span>
        <span className="font-medium">{String(a.payload.stage)}</span>
      </div>
    );
  }
  const cites = (a.payload.citations as string[] | undefined) ?? [];
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-500">
        To
        {a.lead_ids.map((id) => (
          <CitationChip key={id} id={id} />
        ))}
        {cites.length ? (
          <>
            <span className="ml-2">Based on</span>
            {cites.map((id) => (
              <CitationChip key={id} id={id} />
            ))}
          </>
        ) : null}
      </div>
      <div className="rounded border border-ink-200">
        <div className="border-b border-ink-200 px-3 py-1.5 text-sm font-medium">{String(a.payload.subject)}</div>
        <p className="whitespace-pre-line px-3 py-2 text-sm text-ink-700">{String(a.payload.body)}</p>
      </div>
      <p className="text-2xs text-ink-500">Sending is simulated: approval logs the touch and updates recency.</p>
    </div>
  );
}
