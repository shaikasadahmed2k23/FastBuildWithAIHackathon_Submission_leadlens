"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ChevronRight, CornerDownLeft, XCircle } from "lucide-react";
import { useSearchParams } from "next/navigation";
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

const MAX_TABLE_ROWS = 50;

export default function AskPage() {
  return (
    <React.Suspense fallback={<PageHeader title="Ask" />}>
      <Ask />
    </React.Suspense>
  );
}

function Ask() {
  const [question, setQuestion] = React.useState("");
  const [history, setHistory] = React.useState<AskResult[]>([]);
  const inputRef = React.useRef<HTMLInputElement>(null);
  const qc = useQueryClient();
  // Same list the pre-warm script caches, so clicking an example costs no tokens.
  const examples = useQuery({ queryKey: ["ask-examples"], queryFn: api.askExamples, staleTime: Infinity });

  const ask = useMutation({
    mutationFn: api.ask,
    onSuccess: (r) => {
      setHistory((h) => [r, ...h]);
      setQuestion("");
    },
    // The answer may have revealed that the LLM is up or down; refresh the mode indicator.
    onSettled: () => qc.invalidateQueries({ queryKey: ["health"] }),
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

  // Deep link: /ask?q=... runs the question once on load.
  const initial = useSearchParams().get("q");
  const ran = React.useRef(false);
  React.useEffect(() => {
    if (initial && !ran.current) {
      ran.current = true;
      ask.mutate(initial);
    }
  }, [initial, ask]);

  return (
    <>
      <PageHeader title="Ask" description="Plain-English questions, answered with SQL and cited rows" />
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
              {(examples.data ?? []).map((ex) => (
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
          <AnswerCard key={history.length - i} result={r} onAsk={submit} />
        ))}
      </div>
    </>
  );
}

/** Which path produced this answer, stated plainly. */
function AnsweredBy({ result: r }: { result: AskResult }) {
  const provider = r.provider ? r.provider.charAt(0).toUpperCase() + r.provider.slice(1) : "LLM";
  let label: string;
  let tone = "text-zinc-500";
  if (r.source === "llm" && r.fallback === "template") {
    label = `SQL by ${provider} · template answer (LLM prose failed checks)`;
    tone = "text-amber-700";
  } else if (r.source === "llm") {
    label = `LLM: ${provider}`;
  } else if (r.fallback === "rules") {
    label = r.source === "rules" ? "Rule-based fallback (LLM failed)" : "Unanswered (LLM failed)";
    tone = "text-amber-700";
  } else {
    label = r.source === "rules" ? "Rule-based fallback" : "Unanswered";
  }
  const retries = Math.max(0, r.attempts - 1) + Math.max(0, r.answer_attempts - 1);
  return (
    <span className={cn("shrink-0 text-2xs", tone)}>
      {label}
      {retries ? ` · ${retries} ${retries === 1 ? "retry" : "retries"}` : ""}
      {r.cached ? " · cached, 0 tokens" : r.tokens ? ` · ${r.tokens.toLocaleString()} tokens` : ""}
    </span>
  );
}

function AnswerCard({ result: r, onAsk }: { result: AskResult; onAsk: (q: string) => void }) {
  const [showSql, setShowSql] = React.useState(true);
  const idColumns = React.useMemo(
    () => new Set(r.columns.filter((c) => r.rows.some((row) => /^(LD|CO|ACT|ISS)-\d+$/.test(String(row[c] ?? ""))))),
    [r],
  );
  // JSON drops trailing zeros (93.0 arrives as 93), so pad each numeric column to its widest fraction, max 2.
  const decimals = React.useMemo(() => {
    const d: Record<string, number> = {};
    for (const c of r.columns) {
      d[c] = Math.min(2, Math.max(0, ...r.rows.map((row) => {
        const v = row[c];
        return typeof v === "number" && !Number.isInteger(v) ? (String(v).split(".")[1]?.length ?? 0) : 0;
      })));
    }
    return d;
  }, [r]);
  const numeric = (c: string) => r.rows.some((row) => typeof row[c] === "number") && r.rows.every((row) => row[c] == null || typeof row[c] === "number");
  return (
    <article className="rounded border border-zinc-200 bg-white">
      <header className="flex items-start justify-between gap-3 border-b border-zinc-200 px-4 py-2.5">
        <h2 className="text-sm font-medium">{r.question}</h2>
        <AnsweredBy result={r} />
      </header>

      <div className="space-y-3 px-4 py-3">
        {r.suggestions?.length ? (
          <div className="space-y-2">
            <p className="text-sm leading-6">Live model unavailable right now. In offline mode I can answer questions like:</p>
            <div className="flex flex-wrap gap-1.5">
              {r.suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => onAsk(s)}
                  className="rounded border border-zinc-200 bg-white px-2.5 py-1 text-sm text-zinc-700 hover:border-zinc-300 hover:bg-zinc-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="text-sm leading-6">
            <CitedText text={r.answer} />
          </p>
        )}
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
                    <th key={c} className={cn("whitespace-nowrap px-4 py-1.5 font-mono font-normal", numeric(c) && "text-right")}>
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
                        <td key={c} className={cn("tnum whitespace-nowrap px-4 py-1.5 text-zinc-800", numeric(c) && "text-right")}>
                          {v == null ? (
                            <span className="text-zinc-400">null</span>
                          ) : idColumns.has(c) ? (
                            <CitationChip id={String(v)} />
                          ) : typeof v === "number" ? (
                            <span className="font-mono text-xs">{v.toFixed(decimals[c])}</span>
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
