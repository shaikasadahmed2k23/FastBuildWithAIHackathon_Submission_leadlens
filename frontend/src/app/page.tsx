"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { Upload } from "lucide-react";

import { issueLabel, StageBadge } from "@/components/badges";
import { ImportSheet } from "@/components/import-sheet";
import { useInspector } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { ScoreCell } from "@/components/score-bar";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Overview } from "@/lib/api";
import { fmt } from "@/lib/utils";

export default function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const [importing, setImporting] = React.useState(false);
  return (
    <>
      <PageHeader
        title="Overview"
        description={q.data ? `CRM snapshot as of ${fmt.date(q.data.as_of)}` : undefined}
        actions={
          <Button size="sm" onClick={() => setImporting(true)}>
            <Upload /> Import CSV
          </Button>
        }
      />
      <ImportSheet open={importing} onOpenChange={setImporting} />
      <div className="space-y-4 p-6">
        {q.isLoading ? (
          <OverviewSkeleton />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data ? (
          <OverviewBody data={q.data} />
        ) : null}
      </div>
    </>
  );
}

function OverviewSkeleton() {
  return (
    <>
      <div className="grid grid-cols-5 gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-[74px]" />
        ))}
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Skeleton className="col-span-2 h-80" />
        <Skeleton className="h-80" />
      </div>
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="rounded border border-ink-200 bg-panel px-4 py-3">
      <div className="text-xs text-ink-500">{label}</div>
      <div className="tnum mt-1 text-xl font-semibold tracking-tight">{value}</div>
      {sub ? <div className="mt-0.5 text-2xs text-ink-500">{sub}</div> : null}
    </div>
  );
}

function OverviewBody({ data }: { data: Overview }) {
  const { totals } = data;
  const { open } = useInspector();
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label="Leads" value={fmt.int(totals.leads)} sub={`${fmt.int(totals.open_leads)} open · ${fmt.int(totals.companies)} companies`} />
        <Stat label="Open pipeline" value={fmt.money(totals.open_pipeline)} sub="Sum of deal value, open stages" />
        <Stat label="Average score" value={fmt.score(totals.avg_score)} sub="Fit 40 · Intent 40 · Recency 20" />
        <Stat
          label="Clean records"
          value={`${totals.clean_pct.toFixed(1)}%`}
          sub={`${fmt.int(totals.leads_with_issues)} leads have an issue`}
        />
        <Stat
          label="Pending approvals"
          value={fmt.int(totals.pending_actions)}
          sub={
            <Link href="/approvals" className="text-accent hover:underline">
              Review queue
            </Link>
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Panel
          title="Top open leads"
          className="xl:col-span-2"
          actions={
            <Link href="/leads" className="text-xs text-accent hover:underline">
              All leads
            </Link>
          }
        >
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-left text-xs text-ink-500">
                <th className="px-3 py-2 font-normal">Lead</th>
                <th className="px-3 py-2 font-normal">Company</th>
                <th className="px-3 py-2 font-normal">Stage</th>
                <th className="px-3 py-2 font-normal">Owner</th>
                <th className="px-3 py-2 text-right font-normal">F/I/R</th>
                <th className="px-3 py-2 font-normal">Score</th>
              </tr>
            </thead>
            <tbody>
              {data.top_leads.map((l) => (
                <tr
                  key={l.lead_id}
                  onClick={() => open(l.lead_id)}
                  className="cursor-pointer border-b border-ink-100 last:border-0 hover:bg-ink-50"
                >
                  <td className="px-3 py-2">
                    <div className="whitespace-nowrap font-medium">{l.name}</div>
                    <div className="font-mono text-2xs text-ink-500">{l.lead_id}</div>
                  </td>
                  <td className="max-w-[128px] truncate px-3 py-2 text-ink-700" title={l.company}>
                    {l.company}
                  </td>
                  <td className="px-3 py-2">
                    <StageBadge stage={l.stage} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-700">{l.owner}</td>
                  <td className="tnum whitespace-nowrap px-3 py-2 text-right font-mono text-xs text-ink-500">
                    {l.fit.toFixed(0)}/{l.intent.toFixed(0)}/{l.recency.toFixed(0)}
                  </td>
                  <td className="px-3 py-2">
                    <ScoreCell score={l.score} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div className="space-y-4">
          <Panel title="Data health">
            <ul className="divide-y divide-ink-100">
              {data.issues.map((i) => (
                <li key={i.issue_type}>
                  <Link
                    href={`/leads?issue=${i.issue_type}`}
                    className="flex items-center justify-between px-3 py-2 text-sm hover:bg-ink-50"
                  >
                    <span className="text-ink-700">{issueLabel(i.issue_type)}</span>
                    <span className="tnum font-mono text-xs">{fmt.int(i.count)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Score distribution" bodyClassName="p-3">
            <Histogram buckets={data.score_histogram} />
          </Panel>
        </div>
      </div>

      <Panel title="Pipeline by stage">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-ink-200 text-left text-xs text-ink-500">
              <th className="px-3 py-2 font-normal">Stage</th>
              <th className="px-3 py-2 text-right font-normal">Leads</th>
              <th className="px-3 py-2 text-right font-normal">Share</th>
              <th className="px-3 py-2 text-right font-normal">Avg score</th>
            </tr>
          </thead>
          <tbody>
            {data.stages.map((s) => (
              <tr key={s.stage} className="border-b border-ink-100 last:border-0">
                <td className="px-3 py-2">
                  <Link href={`/leads?stage=${s.stage}`} className="hover:underline">
                    <StageBadge stage={s.stage} />
                  </Link>
                </td>
                <td className="tnum px-3 py-2 text-right font-mono text-xs">{fmt.int(s.count)}</td>
                <td className="tnum px-3 py-2 text-right font-mono text-xs text-ink-500">
                  {fmt.pct(s.count / totals.leads)}
                </td>
                <td className="tnum px-3 py-2 text-right font-mono text-xs">{fmt.score(s.avg_score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

function Histogram({ buckets }: { buckets: Overview["score_histogram"] }) {
  const [hover, setHover] = React.useState<number | null>(null);
  const all = Array.from({ length: 10 }, (_, i) => buckets.find((b) => b.bucket === i * 10)?.count ?? 0);
  const max = Math.max(...all, 1);
  const active = hover ?? all.indexOf(max);
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between text-xs">
        <span className="text-ink-500">
          Score {active * 10}–{active * 10 + (active === 9 ? 10 : 9.9)}
        </span>
        <span className="tnum font-mono">{fmt.int(all[active])} leads</span>
      </div>
      <div className="flex h-28 items-end gap-[2px] border-b border-ink-200" role="img" aria-label="Lead count per score band">
        {all.map((count, i) => (
          <div
            key={i}
            className="flex h-full flex-1 cursor-default items-end"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            title={`${i * 10}–${i * 10 + 9}: ${count} leads`}
          >
            <div
              className={`w-full rounded-t-[4px] ${i === active ? "bg-ink-900" : "bg-ink-400"}`}
              style={{ height: `${Math.max((count / max) * 100, count ? 2 : 0)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="tnum mt-1 flex justify-between font-mono text-2xs text-ink-400">
        <span>0</span>
        <span>50</span>
        <span>100</span>
      </div>
    </div>
  );
}
