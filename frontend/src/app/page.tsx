"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";

import { IssueBadge, StageBadge } from "@/components/badges";
import { ImportSheet } from "@/components/import-sheet";
import { useInspector } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { ScoreCell } from "@/components/score-bar";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { api, CALL_SHEET_MIN_SCORE, type Overview } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

export default function OverviewPage() {
  const q = useQuery({ queryKey: ["overview"], queryFn: api.overview });
  const [importing, setImporting] = React.useState(false);
  return (
    <>
      <PageHeader
        title="Overview"
        actions={
          <Button size="sm" onClick={() => setImporting(true)}>
            Import CSV
          </Button>
        }
      />
      <ImportSheet open={importing} onOpenChange={setImporting} />
      <div className="px-8 pb-10 pt-6">
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
    <div className="space-y-6">
      <Skeleton className="h-36" />
      <div className="grid grid-cols-3 gap-8">
        <Skeleton className="col-span-2 h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

/** "Tue 15 Sep 2026", built from parts so no locale abbreviates it differently. */
function dateLine(iso: string) {
  const d = new Date(iso);
  const part = (o: Intl.DateTimeFormatOptions) => d.toLocaleDateString("en-US", o);
  return `${part({ weekday: "short" })} ${part({ day: "numeric" })} ${part({ month: "short" })} ${part({ year: "numeric" })}`;
}

function Masthead({ data }: { data: Overview }) {
  const { totals } = data;
  // Same filters as the Leads API: open stages, score at or above the threshold.
  const calls = useQuery({ queryKey: ["overview", "call-sheet"], queryFn: () => api.callSheet() });
  const stats: { label: string; value: React.ReactNode; sub: React.ReactNode }[] = [
    { label: "Leads", value: fmt.int(totals.leads), sub: `${fmt.int(totals.open_leads)} open · ${fmt.int(totals.companies)} companies` },
    { label: "Open pipeline", value: fmt.money(totals.open_pipeline), sub: "Deal value, open stages" },
    { label: "Average score", value: fmt.score(totals.avg_score), sub: "Fit 40 · Intent 40 · Recency 20" },
    { label: "Clean records", value: `${totals.clean_pct.toFixed(1)}%`, sub: `${fmt.int(totals.leads_with_issues)} leads have an issue` },
    {
      label: "Pending approvals",
      value: fmt.int(totals.pending_actions),
      sub: (
        <Link href="/approvals" className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
          Review queue
        </Link>
      ),
    },
  ];
  return (
    <header>
      <div className="smallcaps flex items-baseline justify-between border-y border-ink py-1.5 text-sm text-ink-600">
        <span>Call sheet · {dateLine(data.as_of)}</span>
        <span>CRM snapshot as of {fmt.date(data.as_of)}</span>
      </div>
      <div className="py-6">
        <h2 className="font-serif text-[44px] font-semibold leading-[1.05] tracking-tight">
          <span className="tnum">{calls.data ? fmt.int(calls.data.total) : "—"}</span> leads to call today
        </h2>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-ink-600">
          Open leads scoring {CALL_SHEET_MIN_SCORE} or more on fit, intent and recency. Scores are computed in SQL and every
          point is cited to a CRM row; the call sheet below starts with the highest.
        </p>
      </div>
      <dl className="grid grid-cols-5 divide-x divide-rule border-y border-rule">
        {stats.map((s) => (
          <div key={s.label} className="min-w-0 px-4 py-3 first:pl-0">
            <dt className="smallcaps text-xs font-semibold text-ink-500">{s.label}</dt>
            <dd className="tnum mt-1 truncate font-serif text-[22px] leading-7">{s.value}</dd>
            <dd className="mt-0.5 truncate text-2xs text-ink-500">{s.sub}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
}

function OverviewBody({ data }: { data: Overview }) {
  const { totals } = data;
  const { open } = useInspector();
  return (
    <div className="space-y-9">
      <Masthead data={data} />

      <div className="grid grid-cols-1 gap-x-10 gap-y-9 xl:grid-cols-3">
        <Panel
          title="Today's call sheet"
          className="xl:col-span-2"
          actions={
            <Link href="/leads" className="text-xs text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent">
              All leads
            </Link>
          }
        >
          <ol>
            {data.top_leads.map((l, i) => (
              <li key={l.lead_id} className="border-b border-rule last:border-0">
                <button
                  type="button"
                  onClick={() => open(l.lead_id)}
                  className="block w-full px-1 py-2.5 text-left hover:bg-panel"
                >
                  <div className="flex items-baseline gap-3">
                    <span className="tnum w-6 shrink-0 font-mono text-xs text-ink-500">{String(i + 1).padStart(2, "0")}</span>
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{l.name}</span>
                      <span className="text-ink-500">, {l.company}</span>
                    </span>
                    <span aria-hidden className="min-w-6 flex-1 border-b border-dotted border-ink-300" />
                    <ScoreCell score={l.score} className="self-center" />
                  </div>
                  <div className="ml-9 mt-1 flex items-center gap-4 text-2xs text-ink-500">
                    <span className="font-mono">{l.lead_id}</span>
                    <StageBadge stage={l.stage} />
                    <span>{l.owner}</span>
                    <span className="tnum font-mono">
                      F/I/R {l.fit.toFixed(0)}/{l.intent.toFixed(0)}/{l.recency.toFixed(0)}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ol>
        </Panel>

        <div className="space-y-9">
          <Panel title="Data health">
            <ul>
              {data.issues.map((i) => (
                <li key={i.issue_type} className="border-b border-rule last:border-0">
                  <Link href={`/leads?issue=${i.issue_type}`} className="flex items-center justify-between px-1 py-2 hover:bg-panel">
                    <IssueBadge issue={i.issue_type} />
                    <span className="tnum font-mono text-xs">{fmt.int(i.count)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel title="Score distribution" bodyClassName="pt-3">
            <Histogram buckets={data.score_histogram} />
          </Panel>
        </div>
      </div>

      <Panel title="Pipeline by stage">
        <table className="w-full text-sm">
          <thead>
            <tr className="smallcaps border-b border-rule text-left text-xs font-semibold text-ink-500">
              <th className="py-2 pl-1 pr-3 font-semibold">Stage</th>
              <th className="px-3 py-2 text-right font-semibold">Leads</th>
              <th className="px-3 py-2 text-right font-semibold">Share</th>
              <th className="py-2 pl-3 pr-1 text-right font-semibold">Avg score</th>
            </tr>
          </thead>
          <tbody>
            {data.stages.map((s) => (
              <tr key={s.stage} className="border-b border-rule last:border-0 even:bg-panel">
                <td className="py-2 pl-1 pr-3">
                  <Link href={`/leads?stage=${s.stage}`} className="hover:underline">
                    <StageBadge stage={s.stage} />
                  </Link>
                </td>
                <td className="tnum px-3 py-2 text-right font-mono text-xs">{fmt.int(s.count)}</td>
                <td className="tnum px-3 py-2 text-right font-mono text-xs text-ink-500">{fmt.pct(s.count / totals.leads)}</td>
                <td className="tnum py-2 pl-3 pr-1 text-right font-mono text-xs">{fmt.score(s.avg_score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

/** Thin ink bars on a baseline; the band holding the median lead is marked in green. */
function Histogram({ buckets }: { buckets: Overview["score_histogram"] }) {
  const [hover, setHover] = React.useState<number | null>(null);
  const all = Array.from({ length: 10 }, (_, i) => buckets.find((b) => b.bucket === i * 10)?.count ?? 0);
  const max = Math.max(...all, 1);
  const total = all.reduce((a, b) => a + b, 0);
  let cum = 0;
  const median = all.findIndex((c) => (cum += c) >= total / 2);
  const active = hover ?? median;
  const band = (i: number) => `${i * 10}–${i === 9 ? 100 : i * 10 + 9}`;
  return (
    <figure>
      <figcaption className="mb-3 flex items-baseline justify-between text-xs">
        <span className="text-ink-600">
          {active === median ? "Median band" : "Band"} {band(active)}
        </span>
        <span className="tnum font-mono">{fmt.int(all[active])} leads</span>
      </figcaption>
      <div className="flex h-28 items-end border-b border-ink" role="img" aria-label={`Leads per score band; median in ${band(median)}`}>
        {all.map((count, i) => (
          <div
            key={i}
            className="flex h-full flex-1 cursor-default items-end justify-center"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
            title={`${band(i)}: ${fmt.int(count)} leads`}
          >
            <div
              className={cn("w-[5px]", i === median ? "bg-accent" : "bg-ink", hover === i && i !== median && "bg-ink-600")}
              style={{ height: `${Math.max((count / max) * 100, count ? 2 : 0)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="tnum mt-1 flex font-mono text-2xs text-ink-500">
        {all.map((_, i) => (
          <span key={i} className="flex-1 text-center">
            {i % 2 === 0 ? i * 10 : ""}
          </span>
        ))}
      </div>
      <p className="smallcaps mt-1 text-center text-xs text-ink-500">Score band</p>
    </figure>
  );
}
