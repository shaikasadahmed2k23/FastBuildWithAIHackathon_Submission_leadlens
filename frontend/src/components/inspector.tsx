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
        "inline-flex h-[18px] items-center rounded border border-zinc-200 bg-zinc-50 px-1 align-baseline font-mono text-[11px] leading-none text-zinc-700",
        clickable && "hover:border-accent/40 hover:bg-accent-subtle hover:text-accent",
        className,
      )}
    >
      {id}
    </button>
  );
}

/** Renders text, turning every [ID] citation into a clickable chip. */
export function CitedText({ text, className }: { text: string; className?: string }) {
  const parts = text.split(/\[?\b((?:LD|CO|ACT|ISS|AX)-\d{4,6})\b\]?/g);
  return (
    <span className={className}>
      {parts.map((part, i) => (i % 2 === 1 ? <CitationChip key={i} id={part} className="mx-0.5" /> : part))}
    </span>
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
          <dl className="divide-y divide-zinc-100 rounded border border-zinc-200">
            {Object.entries(q.data.row).map(([k, v]) => {
              const str = v == null ? "" : String(v);
              return (
                <div key={k} className="grid grid-cols-[140px_1fr] gap-2 px-3 py-1.5">
                  <dt className="font-mono text-xs text-zinc-500">{k}</dt>
                  <dd className="min-w-0 break-words text-sm">
                    {str === "" ? (
                      <span className="text-zinc-400">null</span>
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
