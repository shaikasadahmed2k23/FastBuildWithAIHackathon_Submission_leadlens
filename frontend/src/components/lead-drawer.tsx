"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitMerge, Mail } from "lucide-react";
import * as React from "react";

import { IssueBadge, StageBadge, StatusBadge } from "@/components/badges";
import { CitationChip, CitedText, Footnoted, Sources } from "@/components/inspector";
import { Ticks } from "@/components/score-bar";
import { ErrorState } from "@/components/states";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api, STAGES, type ActionType, type Component, type LeadDetail, type Stage } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

export function LeadDrawer({ leadId, onClose }: { leadId: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["lead", leadId], queryFn: () => api.lead(leadId!), enabled: !!leadId });
  const lead = q.data?.lead;
  return (
    <Sheet
      open={!!leadId}
      onOpenChange={(o) => !o && onClose()}
      title={
        lead ? (
          <span>
            {lead.first_name} {lead.last_name} <span className="ml-1 font-mono text-xs text-ink-500">{lead.lead_id}</span>
          </span>
        ) : (
          <span className="font-mono">{leadId}</span>
        )
      }
      description={lead ? [lead.title, lead.company].filter(Boolean).join(" · ") : undefined}
    >
      {q.isLoading ? (
        <DrawerSkeleton />
      ) : q.isError ? (
        <div className="p-4">
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </div>
      ) : q.data ? (
        <LeadBody detail={q.data} />
      ) : null}
    </Sheet>
  );
}

function DrawerSkeleton() {
  return (
    <div className="space-y-4 p-4">
      <Skeleton className="h-16" />
      <Skeleton className="h-10" />
      <Skeleton className="h-40" />
      <Skeleton className="h-32" />
    </div>
  );
}

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="border-b border-rule px-5 py-4 last:border-b-0">
      <div className="mb-2.5 flex items-center justify-between">
        <h3 className="smallcaps text-sm font-semibold text-ink">{title}</h3>
        {aside}
      </div>
      {children}
    </section>
  );
}

function LeadBody({ detail }: { detail: LeadDetail }) {
  const { lead, breakdown, issues, activities, actions } = detail;
  return (
    <div>
      <div className="grid grid-cols-[0.8fr_1fr_1.5fr_1fr] divide-x divide-rule border-b border-rule">
        {[
          ["Score", breakdown.score.toFixed(1)],
          ["Stage", <StageBadge key="s" stage={lead.stage} />],
          ["Owner", lead.owner],
          ["Deal value", fmt.money(lead.deal_value)],
        ].map(([label, value]) => (
          <div key={label as string} className="px-5 py-3">
            <div className="smallcaps text-xs font-semibold text-ink-500">{label}</div>
            <div className="tnum mt-1 truncate font-serif text-base leading-6">{value}</div>
          </div>
        ))}
      </div>

      <WhyNow leadId={lead.lead_id} />
      <ActionBar detail={detail} />

      <Section title="Score breakdown" aside={<span className="font-mono text-xs text-ink-500">{breakdown.score.toFixed(1)} / 100</span>}>
        <div className="space-y-4">
          <ComponentRow name="Fit" comp={breakdown.fit} />
          <ComponentRow name="Intent" comp={breakdown.intent} />
          <ComponentRow name="Recency" comp={breakdown.recency} />
        </div>
      </Section>

      {issues.length > 0 ? (
        <Section title="Data issues">
          <ul className="space-y-1.5">
            {issues.map((i) => (
              <li key={i.issue_id} className="flex items-start gap-2 text-sm">
                <IssueBadge issue={i.issue_type} />
                <CitedText text={i.details} className="text-ink-700" />
                <CitationChip id={i.issue_id} className="ml-auto shrink-0" />
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      <Section title="Contact">
        <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1 text-sm">
          {(
            [
              ["Email", lead.email],
              ["Phone", lead.phone],
              ["Title", lead.title],
              ["Company", `${lead.company} · ${lead.industry} · ${fmt.int(lead.employees)} employees · ${lead.country}`],
              ["Source", fmt.label(lead.source)],
              ["Created", fmt.date(lead.created_at)],
              ["Last contacted", lead.last_contacted_at ? fmt.date(lead.last_contacted_at) : "Never"],
            ] as const
          ).map(([k, v]) => (
            <React.Fragment key={k}>
              <dt className="text-ink-500">{k}</dt>
              <dd className="min-w-0 truncate">{v && v.trim() ? v : <span className="smallcaps text-pending-ink">missing</span>}</dd>
            </React.Fragment>
          ))}
        </dl>
      </Section>

      <Section title={`Activity (${activities.length}${activities.length === 50 ? "+" : ""})`}>
        {activities.length === 0 ? (
          <p className="text-sm text-ink-500">No recorded activity.</p>
        ) : (
          <ul className="divide-y divide-dotted divide-rule">
            {activities.map((a) => (
              <li key={a.activity_id} className="flex items-center gap-3 py-1.5 text-sm">
                <CitationChip id={a.activity_id} className="w-[68px] shrink-0" />
                <span className="text-ink-700">{fmt.label(a.type)}</span>
                <span className="tnum ml-auto text-xs text-ink-500">{fmt.dateTime(a.occurred_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {actions.length > 0 ? (
        <Section title="Actions">
          <ul className="space-y-1.5">
            {actions.map((a) => (
              <li key={a.action_id} className="flex items-center gap-2 text-sm">
                <span className="font-mono text-xs text-ink-500">{a.action_id}</span>
                <span>{fmt.label(a.type)}</span>
                <StatusBadge status={a.status} />
                <span className="tnum ml-auto text-xs text-ink-500">{fmt.dateTime(a.created_at)}</span>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

function ComponentRow({ name, comp }: { name: string; comp: Component }) {
  const [expanded, setExpanded] = React.useState(false);
  const shown = expanded ? comp.contributions : comp.contributions.slice(0, 4);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-serif text-base">{name}</span>
        <span className="tnum font-mono text-xs text-ink-600">
          {comp.points.toFixed(1)} / {comp.max_points}
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-3">
        <Ticks value={comp.points} max={comp.max_points} />
        <p className="truncate text-xs text-ink-500">{comp.summary}</p>
      </div>
      {comp.contributions.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {shown.map((c, i) => (
            <li key={`${c.ref}-${c.field}-${i}`} className="flex items-baseline gap-2 border-b border-dotted border-rule py-0.5 text-xs last:border-0">
              <CitationChip id={c.ref} className="w-[68px] shrink-0" />
              <span className="text-ink-600">{fmt.label(c.field)}</span>
              <span className="truncate text-ink-500">{c.value}</span>
              <span className="tnum ml-auto font-mono text-ink-700">+{c.points.toFixed(1)}</span>
            </li>
          ))}
          {comp.contributions.length > 4 ? (
            <li>
              <button className="text-xs text-accent hover:underline" onClick={() => setExpanded((e) => !e)}>
                {expanded ? "Show fewer" : `Show all ${comp.contributions.length}`}
              </button>
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}

function WhyNow({ leadId }: { leadId: string }) {
  const q = useQuery({ queryKey: ["explain", leadId], queryFn: () => api.explain(leadId), staleTime: Infinity });
  return (
    <Section
      title="Why now"
      aside={
        q.data ? (
          <span className={cn("text-2xs", q.data.valid ? "text-accent" : "text-alert")}>
            {q.data.valid ? `${q.data.citations.length} citations verified` : "Citations failed verification"}
            {q.data.source === "template" ? " · rule-based" : ""}
          </span>
        ) : null
      }
    >
      {q.isLoading ? (
        <div className="space-y-1.5">
          <Skeleton className="h-4" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => q.refetch()} />
      ) : q.data ? (
        <>
          <p className="font-serif text-[15px] leading-7 text-ink">
            <Footnoted text={q.data.why_now} />
          </p>
          <Sources text={q.data.why_now} className="mt-3" />
        </>
      ) : null}
    </Section>
  );
}

function ActionBar({ detail }: { detail: LeadDetail }) {
  const { lead, issues } = detail;
  const toast = useToast();
  const qc = useQueryClient();
  const [stage, setStage] = React.useState<Stage>(lead.stage);
  const duplicateOf = issues.find((i) => i.issue_type === "duplicate" && i.related_lead_id && i.related_lead_id !== lead.lead_id);
  const pending = detail.actions.filter((a) => a.status === "pending");

  const create = useMutation({
    mutationFn: (body: { type: ActionType; lead_ids: string[]; payload?: Record<string, unknown> }) =>
      api.createAction({ ...body, actor: "reviewer" }),
    onSuccess: (a) => {
      toast(`${a.action_id} sent to approvals`);
      qc.invalidateQueries({ queryKey: ["lead", lead.lead_id] });
      qc.invalidateQueries({ queryKey: ["actions"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Failed to create action", "error"),
  });

  return (
    <Section
      title="Propose an action"
      aside={pending.length ? <span className="text-2xs text-pending-ink">{pending.length} pending approval</span> : null}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={create.isPending}
          onClick={() => create.mutate({ type: "outreach", lead_ids: [lead.lead_id] })}
        >
          <Mail /> Draft outreach
        </Button>
        {duplicateOf?.related_lead_id ? (
          <Button
            size="sm"
            disabled={create.isPending}
            onClick={() =>
              create.mutate({
                type: "merge",
                lead_ids: [duplicateOf.related_lead_id!, lead.lead_id],
                payload: { primary_id: duplicateOf.related_lead_id },
              })
            }
          >
            <GitMerge /> Merge into {duplicateOf.related_lead_id}
          </Button>
        ) : null}
        <div className="ml-auto flex items-center gap-1.5">
          <Select value={stage} onChange={(e) => setStage(e.target.value as Stage)} className="h-7 text-xs" aria-label="New stage">
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            disabled={create.isPending || stage === lead.stage}
            onClick={() => create.mutate({ type: "stage_change", lead_ids: [lead.lead_id], payload: { stage } })}
          >
            Change stage
          </Button>
        </div>
      </div>
      <p className="mt-2 text-2xs text-ink-500">Nothing changes in the CRM until a reviewer approves it.</p>
    </Section>
  );
}
