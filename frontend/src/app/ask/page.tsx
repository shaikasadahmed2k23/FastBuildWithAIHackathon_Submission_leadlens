"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, CornerDownLeft, XCircle } from "lucide-react";
import * as React from "react";

import { CitationChip, CitedText } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AskResult } from "@/lib/api";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "Top 10 open leads in Fintech",
  "How many stale leads does each owner have?",
  "Which Healthcare leads had a meeting in the last 2 days?",
  "Average lead score by industry",
  "How many leads are missing a phone number?",
  "Total open pipeline deal value by owner",
];
const MAX_TABLE_ROWS = 50;

export default function AskPage() {
  const [question, setQuestion] = React.useState("");
  const [history, setHistory] = React.useState<AskResult[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  const ask = useMutation({
    mutationFn: api.ask,
    onSuccess: (r) => {
      setHistory((h) => [r, ...h]);
      setQuestion("");
    },
  });

  React.useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement).tagName);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (q: string) => {
    if (q.trim().length >= 3 && !ask.isPending) ask.mutate(q.trim());
  };

  return (
    <>
      <PageHeader
        title="Ask"
        description="Plain-English questions, answered with SQL and cited rows"
        actions={
          health.data?.mode === "offline" ? (
            <span className="text-2xs text-amber-700">Offline: rule-based answers for common questions</span>
          ) : null
        }
      />
      <div className="mx-auto max-w-4xl space-y-4 p-6">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
          className="flex gap-2"
        >
          <Input
            ref={inputRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. Which leads requested a demo in the last 7 days?"
            className="h-9"
            maxLength={500}
            aria-label="Question"
          />
          <Button type="submit" variant="primary" className="h-9" disabled={ask.isPending || question.trim().length < 3}>
            Ask <CornerDownLeft />
          </Button>
        </form>

        {history.length === 0 && !ask.isPending ? (
          <div>
            <p className="mb-2 text-xs text-zinc-500">
              Try one of these, or press <Kbd>/</Kbd> to type your own.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => submit(ex)}
                  className="rounded border border-zinc-200 bg-white px-2.5 py-1 text-sm text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {ask.isPending ? (
          <div className="space-y-2 rounded border border-zinc-200 p-4">
            <p className="text-sm text-zinc-500">Writing SQL, running it, and checking citations…</p>
            <Skeleton className="h-4" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-24" />
          </div>
        ) : null}
        {ask.isError ? <ErrorState error={ask.error} onRetry={() => ask.reset()} /> : null}

        {history.map((r, i) => (
          <AnswerCard key={history.length - i} result={r} />
        ))}
      </div>
    </>
  );
}

function AnswerCard({ result: r }: { result: AskResult }) {
  const [showSql, setShowSql] = React.useState(true);
  const idColumns = React.useMemo(
    () => new Set(r.columns.filter((c) => r.rows.some((row) => /^(LD|CO|ACT|ISS)-\d+$/.test(String(row[c] ?? ""))))),
    [r],
  );
  return (
    <article className="rounded border border-zinc-200 bg-white">
      <header className="flex items-start justify-between gap-3 border-b border-zinc-200 px-4 py-2.5">
        <h2 className="text-sm font-medium">{r.question}</h2>
        <span className="shrink-0 text-2xs text-zinc-500">
          {r.source === "llm" ? `LLM${r.provider ? ` · ${r.provider}` : ""}` : r.source === "rules" ? "Rule-based" : "Unanswered"}
          {r.attempts > 1 ? ` · ${r.attempts} attempts` : ""}
        </span>
      </header>

      <div className="space-y-3 px-4 py-3">
        <p className="text-sm leading-6">
          <CitedText text={r.answer} />
        </p>
        <div
          className={cn(
            "flex items-center gap-1.5 text-xs",
            r.valid ? "text-emerald-700" : r.sql ? "text-red-700" : "text-zinc-500",
          )}
        >
          {r.valid ? <CheckCircle2 className="size-3.5" /> : <XCircle className="size-3.5" />}
          {r.valid
            ? r.citations.length
              ? `Verified: ${r.citations.length} cited ${r.citations.length === 1 ? "row" : "rows"} and every number found in the query result`
              : "Verified: every number found in the query result"
            : r.sql
              ? "Not verified: the answer cites rows or numbers missing from the query result"
              : "No query was run"}
        </div>
        {r.notes.length ? (
          <ul className="space-y-0.5 text-2xs text-zinc-500">
            {r.notes.map((n, i) => (
              <li key={i}>· {n}</li>
            ))}
          </ul>
        ) : null}
      </div>

      {r.sql ? (
        <div className="border-t border-zinc-200">
          <button
            onClick={() => setShowSql((s) => !s)}
            className="flex w-full items-center gap-1 px-4 py-2 text-xs text-zinc-500 hover:text-zinc-900"
          >
            <ChevronRight className={cn("size-3.5 transition-transform", showSql && "rotate-90")} />
            SQL
          </button>
          {showSql ? (
            <pre className="mx-4 mb-3 overflow-x-auto whitespace-pre-wrap break-words rounded border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs leading-5 text-zinc-800">
              {r.sql}
            </pre>
          ) : null}
        </div>
      ) : null}

      {r.rows.length ? (
        <div className="border-t border-zinc-200">
          <div className="px-4 py-2 text-xs text-zinc-500">
            {r.rows.length} {r.rows.length === 1 ? "row" : "rows"}
            {r.rows.length > MAX_TABLE_ROWS ? `, showing first ${MAX_TABLE_ROWS}` : ""}
          </div>
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                  {r.columns.map((c) => (
                    <th key={c} className="whitespace-nowrap px-4 py-1.5 font-mono font-normal">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {r.rows.slice(0, MAX_TABLE_ROWS).map((row, i) => (
                  <tr key={i} className="border-b border-zinc-100 last:border-0">
                    {r.columns.map((c) => {
                      const v = row[c];
                      return (
                        <td key={c} className="tnum whitespace-nowrap px-4 py-1.5 text-zinc-800">
                          {v == null ? (
                            <span className="text-zinc-400">null</span>
                          ) : idColumns.has(c) ? (
                            <CitationChip id={String(v)} />
                          ) : typeof v === "number" ? (
                            <span className="font-mono text-xs">{v}</span>
                          ) : (
                            String(v)
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </article>
  );
}
