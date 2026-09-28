"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, XCircle } from "lucide-react";
import * as React from "react";

import { CitedText } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState } from "@/components/states";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type EvalReport } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

export default function EvalsPage() {
  const q = useQuery({ queryKey: ["evals"], queryFn: api.evals, retry: false });
  return (
    <>
      <PageHeader
        title="Evals"
        description={q.data ? `Last run ${fmt.dateTime(q.data.run_at)} · ${q.data.mode === "full" ? q.data.model : "offline, rule-based"}` : undefined}
      />
      <div className="space-y-4 p-6">
        {q.isLoading ? (
          <>
            <div className="grid grid-cols-4 gap-3">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-[74px]" />
              ))}
            </div>
            <Skeleton className="h-64" />
          </>
        ) : q.error instanceof ApiError && q.error.status === 404 ? (
          <EmptyState title="No eval run yet" hint="Run `python -m evals.run` in backend/ to generate a report." />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data ? (
          <Report data={q.data} />
        ) : null}
      </div>
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-zinc-200 bg-white px-4 py-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="tnum mt-1 text-xl font-semibold tracking-tight">{value}</div>
      {sub ? <div className="mt-0.5 text-2xs text-zinc-500">{sub}</div> : null}
    </div>
  );
}

function Report({ data }: { data: EvalReport }) {
  const s = data.summary;
  const [failuresOnly, setFailuresOnly] = React.useState(false);
  const [expanded, setExpanded] = React.useState<string | null>(null);
  const results = failuresOnly ? data.results.filter((r) => !r.passed) : data.results;

  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Answer accuracy" value={fmt.pct(s.accuracy, 0)} sub={`${s.passed} of ${s.total} golden questions`} />
        <Stat
          label="Citation validity"
          value={fmt.pct(s.citation_valid_rate, 0)}
          sub={`${s.hallucinated_citations} answers failed the checker`}
        />
        <Stat label="Avg latency" value={`${fmt.int(s.avg_latency_ms)} ms`} sub="End to end, per question" />
        <Stat
          label="Answered by"
          value={Object.entries(s.by_source)
            .filter(([, n]) => n)
            .map(([k, n]) => `${n} ${k}`)
            .join(" · ")}
          sub="llm / rules / none"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Data cleaning vs. injected ground truth">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                <th className="px-3 py-2 font-normal">Issue</th>
                <th className="px-3 py-2 text-right font-normal">Precision</th>
                <th className="px-3 py-2 text-right font-normal">Recall</th>
                <th className="px-3 py-2 text-right font-normal">F1</th>
                <th className="px-3 py-2 text-right font-normal">Found / expected</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.cleaning).map(([k, m]) => (
                <tr key={k} className="border-b border-zinc-100 last:border-0">
                  <td className="px-3 py-2">{fmt.label(k)}</td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs">{m.precision.toFixed(3)}</td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs">{m.recall.toFixed(3)}</td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs">{m.f1.toFixed(3)}</td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs text-zinc-500">
                    {m.found} / {m.expected}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Accuracy by category">
          <table className="w-full text-sm">
            <tbody>
              {Object.entries(s.by_category).map(([cat, v]) => (
                <tr key={cat} className="border-b border-zinc-100 last:border-0">
                  <td className="px-3 py-2">{fmt.label(cat)}</td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs">
                    {v.passed} / {v.total}
                  </td>
                  <td className="w-40 px-3 py-2">
                    <div className="h-1 overflow-hidden rounded-full bg-zinc-100">
                      <div className="h-full rounded-full bg-zinc-800" style={{ width: `${(v.passed / v.total) * 100}%` }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      </div>

      <Panel
        title="Golden questions"
        actions={
          <label className="flex items-center gap-1.5 text-xs text-zinc-500">
            <input type="checkbox" checked={failuresOnly} onChange={(e) => setFailuresOnly(e.target.checked)} />
            Failures only
          </label>
        }
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
              <th className="w-8 px-3 py-2" />
              <th className="px-3 py-2 font-normal">ID</th>
              <th className="px-3 py-2 font-normal">Question</th>
              <th className="px-3 py-2 font-normal">Category</th>
              <th className="px-3 py-2 font-normal">Source</th>
              <th className="px-3 py-2 font-normal">Result</th>
              <th className="px-3 py-2 text-right font-normal">ms</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <React.Fragment key={r.id}>
                <tr
                  className="cursor-pointer border-b border-zinc-100 hover:bg-zinc-50"
                  onClick={() => setExpanded((e) => (e === r.id ? null : r.id))}
                >
                  <td className="px-3 py-2 text-zinc-400">
                    <ChevronRight className={cn("size-3.5 transition-transform", expanded === r.id && "rotate-90")} />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-zinc-500">{r.id}</td>
                  <td className="px-3 py-2">{r.question}</td>
                  <td className="px-3 py-2 text-zinc-600">{fmt.label(r.category)}</td>
                  <td className="px-3 py-2 text-zinc-600">{r.source}</td>
                  <td className="px-3 py-2">
                    {r.passed ? (
                      <span className="inline-flex items-center gap-1 text-xs text-emerald-700">
                        <CheckCircle2 className="size-3.5" /> Pass
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-red-700">
                        <XCircle className="size-3.5" /> Fail
                      </span>
                    )}
                  </td>
                  <td className="tnum px-3 py-2 text-right font-mono text-xs text-zinc-500">{r.latency_ms}</td>
                </tr>
                {expanded === r.id ? (
                  <tr className="border-b border-zinc-100 bg-zinc-50/60">
                    <td />
                    <td colSpan={6} className="space-y-2 px-3 py-3">
                      <div className="text-xs text-zinc-500">
                        Expected <span className="font-mono text-zinc-800">{JSON.stringify(r.expected)}</span> · Got{" "}
                        <span className="font-mono text-zinc-800">{JSON.stringify(r.got)}</span>
                      </div>
                      <p className="text-sm">
                        <CitedText text={r.answer} />
                      </p>
                      {r.sql ? (
                        <pre className="overflow-x-auto whitespace-pre-wrap rounded border border-zinc-200 bg-white p-2 font-mono text-xs text-zinc-700">
                          {r.sql}
                        </pre>
                      ) : null}
                    </td>
                  </tr>
                ) : null}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
