"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";

import { LeadDrawer } from "@/components/lead-drawer";
import { ErrorState } from "@/components/states";
import { Sheet } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

type Inspector = { open: (id: string) => void };
const InspectorContext = React.createContext<Inspector>({ open: () => {} });
export const useInspector = () => React.useContext(InspectorContext);

const isCitationId = (s: string) => /^(?:LD|CO|ACT|ISS|AX)-\d{4,6}$/.test(s);

export function InspectorProvider({ children }: { children: React.ReactNode }) {
  const [leadId, setLeadId] = React.useState<string | null>(null);
  const [rowId, setRowId] = React.useState<string | null>(null);
  const open = React.useCallback((id: string) => {
    if (id.startsWith("LD-")) {
      setRowId(null);
      setLeadId(id);
    } else if (!id.startsWith("AX-")) {
      setRowId(id);
    }
  }, []);
  const value = React.useMemo(() => ({ open }), [open]);
  return (
    <InspectorContext.Provider value={value}>
      {children}
      <LeadDrawer leadId={leadId} onClose={() => setLeadId(null)} />
      <RowSheet rowId={rowId} onClose={() => setRowId(null)} />
    </InspectorContext.Provider>
  );
}

/** A row ID as a mono reference; clicking opens the source row. */
export function CitationChip({ id, className }: { id: string; className?: string }) {
  const { open } = useInspector();
  const clickable = !id.startsWith("AX-");
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        open(id);
      }}
      disabled={!clickable}
      title={clickable ? `Open source row ${id}` : id}
      className={cn(
        "inline align-baseline font-mono text-[11px] text-ink-700",
        clickable && "underline decoration-ink-300 decoration-dotted underline-offset-[3px] hover:text-accent hover:decoration-accent",
        className,
      )}
    >
      {id}
    </button>
  );
}

const CITATION = /\[?\b((?:LD|CO|ACT|ISS|AX)-\d{4,6})\b\]?/g;

/** Renders text with every [ID] citation as an inline mono reference (for lists and short notes). */
export function CitedText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(CITATION);
  return (
    <span className={className}>
      {parts.map((part, i) => (i % 2 === 1 ? <CitationChip key={i} id={part} /> : part))}
    </span>
  );
}

type Segment = string | { n: number; id: string };

/**
 * Splits prose into text and numbered footnote markers, one number per distinct ID in order of
 * first appearance. A marker that leads its clause ("[LD-1] Ann, score 90; [LD-2] ...") is moved
 * to the end of that clause so it reads as a footnote. Presentation only; the text is unchanged.
 */
export function footnotes(text: string): { segments: Segment[]; ids: string[] } {
  const parts = text.split(CITATION);
  const ids: string[] = [];
  const number = (id: string) => {
    if (!ids.includes(id)) ids.push(id);
    return ids.indexOf(id) + 1;
  };
  const segments: Segment[] = [];
  for (let i = 0; i < parts.length; i++) {
    if (i % 2 === 0) {
      segments.push(parts[i]);
      continue;
    }
    const marker = { n: number(parts[i]), id: parts[i] };
    const prev = String(segments[segments.length - 1] ?? "");
    const leading = prev === "" || /[:;,(]\s*$|^\s*$/.test(prev);
    const next = parts[i + 1] ?? "";
    const boundary = next.search(/;|\.(?=\s|$)/);
    if (leading && next.trim() && boundary !== 0) {
      const cut = boundary === -1 ? next.trimEnd().length : boundary;
      segments[segments.length - 1] = prev;
      segments.push(next.slice(0, cut).replace(/^\s+/, ""), marker, next.slice(cut));
      i++; // the following text part is consumed
    } else {
      segments[segments.length - 1] = prev.replace(/\s+$/, "");
      segments.push(marker);
    }
  }
  return { segments, ids };
}

function FootnoteRef({ n, id }: { n: number; id: string }) {
  const { open } = useInspector();
  return (
    <sup className="ml-px">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          open(id);
        }}
        disabled={id.startsWith("AX-")}
        title={`Open source row ${id}`}
        aria-label={`Source ${n}: ${id}`}
        className="font-mono text-[10px] font-medium text-accent hover:underline"
      >
        {n}
      </button>
    </sup>
  );
}

/** Prose with superscript footnote numbers; pair with <Sources> for the list. */
export function Footnoted({ text, className }: { text: string; className?: string }) {
  const { segments } = React.useMemo(() => footnotes(text), [text]);
  return (
    <span className={className}>
      {segments.map((s, i) => (typeof s === "string" ? s : <FootnoteRef key={i} n={s.n} id={s.id} />))}
    </span>
  );
}

const TABLE_BY_PREFIX: Record<string, string> = { LD: "lead", CO: "company", ACT: "activity", ISS: "data issue", AX: "action" };

/** The footnote list: number, row ID in mono (opens the row), and a short description. */
export function Sources({
  text,
  describe,
  className,
}: {
  text: string;
  describe?: (id: string) => string | undefined;
  className?: string;
}) {
  const { ids } = React.useMemo(() => footnotes(text), [text]);
  if (!ids.length) return null;
  return (
    <div className={cn("border-t border-rule pt-2", className)}>
      <h4 className="smallcaps mb-1 text-xs font-semibold text-ink-500">Sources</h4>
      <ol className="space-y-0.5 text-xs">
        {ids.map((id, i) => (
          <li key={id} className="flex items-baseline gap-2">
            <span className="tnum w-4 shrink-0 text-right font-mono text-2xs text-accent">{i + 1}</span>
            <CitationChip id={id} />
            <span className="truncate text-ink-500">{describe?.(id) ?? TABLE_BY_PREFIX[id.split("-")[0]]}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RowSheet({ rowId, onClose }: { rowId: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["row", rowId], queryFn: () => api.row(rowId!), enabled: !!rowId });
  const { open } = useInspector();
  return (
    <Sheet
      open={!!rowId}
      onOpenChange={(o) => !o && onClose()}
      title={<span className="font-mono">{rowId}</span>}
      description={q.data ? `Source row in ${q.data.table}` : "Source row"}
      className="max-w-[420px]"
    >
      <div className="p-4">
        {q.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-5" />
            ))}
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        ) : q.data ? (
          <dl className="divide-y divide-rule border-y border-rule">
            {Object.entries(q.data.row).map(([k, v]) => {
              const str = v == null ? "" : String(v);
              return (
                <div key={k} className="grid grid-cols-[140px_1fr] gap-2 px-3 py-1.5">
                  <dt className="font-mono text-xs text-ink-500">{k}</dt>
                  <dd className="min-w-0 break-words text-sm">
                    {str === "" ? (
                      <span className="text-ink-400">null</span>
                    ) : isCitationId(str) && str !== rowId ? (
                      <button className="font-mono text-xs text-accent hover:underline" onClick={() => open(str)}>
                        {str}
                      </button>
                    ) : (
                      <span className="tnum">{str}</span>
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        ) : null}
      </div>
    </Sheet>
  );
}
