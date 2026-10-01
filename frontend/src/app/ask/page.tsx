"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronRight,
  CornerDownLeft,
  XCircle,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import * as React from "react";

import { CitationChip, Footnoted, Sources } from "@/components/inspector";
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
  const examples = useQuery({
    queryKey: ["ask-examples"],
    queryFn: api.askExamples,
    staleTime: Infinity,
  });

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
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(
        (e.target as HTMLElement).tagName,
      );
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
      <PageHeader
        title="Ask"
        description="Plain-English questions, answered with SQL and cited rows"
      />
      <div className="mx-auto max-w-4xl space-y-10 px-8 pb-12 pt-8">
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
            className="h-10 text-base"
            maxLength={500}
            aria-label="Question"
          />
          <Button
            type="submit"
            variant="primary"
            className="h-10 px-4"
            disabled={ask.isPending || question.trim().length < 3}
          >
            Ask <CornerDownLeft />
          </Button>
        </form>

        {history.length === 0 && !ask.isPending ? (
          <div>
            <p className="smallcaps mb-1 text-sm font-semibold text-ink-600">
              Questions on file
            </p>
            <p className="mb-3 text-sm text-ink-500">
              Pick one, or press <Kbd>/</Kbd> to write your own.
            </p>
            <div className="flex flex-wrap gap-2">
              {(examples.data ?? []).map((ex) => (
                <button
                  key={ex}
                  onClick={() => submit(ex)}
                  className="rounded border border-rule bg-panel px-3 py-1.5 text-left text-sm text-ink-700 hover:border-accent hover:text-ink"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {ask.isPending ? (
          <div className="space-y-3 border-t border-ink pt-5">
            <p className="font-serif text-lg italic text-ink-500">
              Writing SQL, running it, and checking citations…
            </p>
            <Skeleton className="h-4" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-24" />
          </div>
        ) : null}
        {ask.isError ? (
          <ErrorState error={ask.error} onRetry={() => ask.reset()} />
        ) : null}

        {history.map((r, i) => (
          <AnswerCard key={history.length - i} result={r} onAsk={submit} />
        ))}
      </div>
    </>
  );
}

/** Which path produced this answer, stated plainly. */
function AnsweredBy({ result: r }: { result: AskResult }) {
  const provider = r.provider
    ? r.provider.charAt(0).toUpperCase() + r.provider.slice(1)
    : "LLM";
  let label: string;
  let tone = "text-ink-500";
  if (r.source === "llm" && r.fallback === "template") {
    label = `SQL by ${provider} · template answer (LLM prose failed checks)`;
    tone = "text-pending-ink";
  } else if (r.source === "llm") {
    label = r.cannot_answer
      ? `LLM: ${provider} · declined`
      : `LLM: ${provider}`;
  } else if (r.fallback === "rules") {
    label =
      r.source === "rules"
        ? "Rule-based fallback (LLM failed)"
        : "Unanswered (LLM failed)";
    tone = "text-pending-ink";
  } else {
    label = r.source === "rules" ? "Rule-based fallback" : "Unanswered";
  }
  const retries =
    Math.max(0, r.attempts - 1) + Math.max(0, r.answer_attempts - 1);
  return (
    <span className={cn("shrink-0 text-2xs", tone)}>
      {label}
      {retries ? ` · ${retries} ${retries === 1 ? "retry" : "retries"}` : ""}
      {r.cached
        ? " · cached, 0 tokens"
        : r.tokens
          ? ` · ${r.tokens.toLocaleString()} tokens`
          : ""}
    </span>
  );
}

/** A short description of a cited row, taken from the query result itself. */
function describeFrom(r: AskResult) {
  return (id: string) => {
    const row = r.rows.find((row) => Object.values(row).includes(id));
    if (!row) return undefined;
    const parts = Object.values(row)
      .filter(
        (v) =>
          v != null && v !== id && !/^(LD|CO|ACT|ISS)-\d+$/.test(String(v)),
      )
      .slice(0, 2)
      .map(String);
    return parts.length ? parts.join(" · ") : undefined;
  };
}

function AnswerCard({
  result: r,
  onAsk,
}: {
  result: AskResult;
  onAsk: (q: string) => void;
}) {
  const [showSql, setShowSql] = React.useState(true);
  const idColumns = React.useMemo(
    () =>
      new Set(
        r.columns.filter((c) =>
          r.rows.some((row) =>
            /^(LD|CO|ACT|ISS)-\d+$/.test(String(row[c] ?? "")),
          ),
        ),
      ),
    [r],
  );
  // JSON drops trailing zeros (93.0 arrives as 93), so pad each numeric column to its widest fraction, max 2.
  const decimals = React.useMemo(() => {
    const d: Record<string, number> = {};
    for (const c of r.columns) {
      d[c] = Math.min(
        2,
        Math.max(
          0,
          ...r.rows.map((row) => {
            const v = row[c];
            return typeof v === "number" && !Number.isInteger(v)
              ? (String(v).split(".")[1]?.length ?? 0)
              : 0;
          }),
        ),
      );
    }
    return d;
  }, [r]);
  const numeric = (c: string) =>
    r.rows.some((row) => typeof row[c] === "number") &&
    r.rows.every((row) => row[c] == null || typeof row[c] === "number");
  const describe = React.useMemo(() => describeFrom(r), [r]);

  return (
    <article className="fade-in space-y-5 border-t border-ink pt-5">
      <header className="flex items-start justify-between gap-6">
        <h2 className="border-l-2 border-accent pl-4 font-serif text-[22px] italic leading-8 text-ink">
          {r.question}
        </h2>
        <AnsweredBy result={r} />
      </header>

      <div className="space-y-3">
        {r.suggestions?.length ? (
          <div className="space-y-3">
            {r.cannot_answer ? (
              <div>
                <p className="font-serif text-lg leading-7">
                  This data can&apos;t answer that.
                </p>
                <p className="mt-1 text-sm leading-6 text-ink-600">
                  {r.cannot_answer}.
                </p>
                <p className="mt-3 text-[15px] leading-7">
                  Here&apos;s what it can answer:
                </p>
              </div>
            ) : (
              <p className="text-[15px] leading-7">
                Live model unavailable right now. In offline mode I can answer
                questions like:
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              {r.suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => onAsk(s)}
                  className="rounded border border-rule bg-panel px-3 py-1.5 text-left text-sm text-ink-700 hover:border-accent hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <p className="max-w-3xl text-[15px] leading-7">
            <Footnoted text={r.answer} />
          </p>
        )}
        {r.cannot_answer ? null : (
          <div
            className={cn(
              "flex items-center gap-1.5 text-xs",
              r.valid ? "text-accent" : r.sql ? "text-alert" : "text-ink-500",
            )}
          >
            {r.valid ? (
              <CheckCircle2 className="size-3.5" />
            ) : (
              <XCircle className="size-3.5" />
            )}
            {r.valid
              ? r.citations.length
                ? `Verified: ${r.citations.length} cited ${r.citations.length === 1 ? "row" : "rows"} and every number found in the query result`
                : "Verified: every number found in the query result"
              : r.sql
                ? "Not verified: the answer cites rows or numbers missing from the query result"
                : "No query was run"}
          </div>
        )}
        {r.notes.length ? (
          <ul className="space-y-0.5 text-2xs text-ink-500">
            {r.notes.map((n, i) => (
              <li key={i}>· {n}</li>
            ))}
          </ul>
        ) : null}
      </div>

      {r.sql ? (
        <section>
          <button
            onClick={() => setShowSql((s) => !s)}
            aria-expanded={showSql}
            className="smallcaps flex items-center gap-1 text-sm font-semibold text-ink-600 hover:text-ink"
          >
            <ChevronRight
              className={cn(
                "size-3.5 transition-transform duration-100",
                showSql && "rotate-90",
              )}
            />
            Appendix · SQL
          </button>
          {showSql ? (
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words border border-rule bg-panel px-4 py-3 font-mono text-xs leading-5 text-ink-800">
              {r.sql}
            </pre>
          ) : null}
        </section>
      ) : null}

      {r.suggestions?.length ? null : (
        <Sources text={r.answer} describe={describe} />
      )}

      {r.rows.length ? (
        <section>
          <h3 className="smallcaps mb-1.5 text-sm font-semibold text-ink-600">
            Result · {r.rows.length} {r.rows.length === 1 ? "row" : "rows"}
            {r.rows.length > MAX_TABLE_ROWS
              ? `, first ${MAX_TABLE_ROWS} shown`
              : ""}
          </h3>
          <div className="max-h-96 overflow-auto border-t border-ink">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-paper">
                <tr className="border-b border-rule text-left text-2xs text-ink-500">
                  {r.columns.map((c) => (
                    <th
                      key={c}
                      className={cn(
                        "whitespace-nowrap px-3 py-1.5 font-mono font-normal first:pl-1",
                        numeric(c) && "text-right",
                      )}
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {r.rows.slice(0, MAX_TABLE_ROWS).map((row, i) => (
                  <tr
                    key={i}
                    className="border-b border-rule last:border-0 even:bg-panel"
                  >
                    {r.columns.map((c) => {
                      const v = row[c];
                      return (
                        <td
                          key={c}
                          className={cn(
                            "tnum whitespace-nowrap px-3 py-1.5 text-ink-800 first:pl-1",
                            numeric(c) && "text-right",
                          )}
                        >
                          {v == null ? (
                            <span className="text-ink-400">null</span>
                          ) : idColumns.has(c) ? (
                            <CitationChip id={String(v)} />
                          ) : typeof v === "number" ? (
                            <span className="font-mono text-xs">
                              {v.toFixed(decimals[c])}
                            </span>
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
        </section>
      ) : null}
    </article>
  );
}
