"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { IssueBadge, StageBadge } from "@/components/badges";
import { useInspector } from "@/components/inspector";
import { PageHeader } from "@/components/page-header";
import { ScoreCell } from "@/components/score-bar";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type LeadRow, STAGES } from "@/lib/api";
import { useHealth } from "@/lib/use-health";
import { cn, daysSince, fmt } from "@/lib/utils";

const PAGE_SIZE = 50;
const OWNERS = ["Aisha Bello", "Daniel Ortiz", "Hana Sato", "Lucas Martin", "Maya Chen", "Priya Nair", "Ravi Kumar", "Tom Becker"];
const INDUSTRIES = ["E-commerce", "Education", "Fintech", "Healthcare", "Logistics", "Manufacturing", "Media", "Software"];
const ISSUES = [
  ["any", "Any issue"],
  ["none", "No issues"],
  ["duplicate", "Duplicate"],
  ["stale", "Stale"],
  ["missing_field", "Missing field"],
] as const;

export default function LeadsPage() {
  return (
    <React.Suspense fallback={<PageHeader title="Leads" />}>
      <Leads />
    </React.Suspense>
  );
}

function useFilters() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const get = (k: string) => params.get(k) ?? "";
  const filters = {
    q: get("q"),
    stage: get("stage"),
    owner: get("owner"),
    industry: get("industry"),
    issue: get("issue"),
    sort: get("sort") || "score",
    order: (get("order") || "desc") as "asc" | "desc",
    page: Number(get("page") || 1),
  };
  const set = React.useCallback(
    (patch: Partial<Record<keyof typeof filters, string | number>>) => {
      const next = new URLSearchParams(params.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v === "" || v === undefined) next.delete(k);
        else next.set(k, String(v));
      }
      if (!("page" in patch)) next.delete("page");
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    },
    [params, pathname, router],
  );
  return { filters, set };
}

function Leads() {
  const { filters, set } = useFilters();
  const { open } = useInspector();
  const health = useHealth();
  const asOf = health.data?.as_of;
  const searchRef = React.useRef<HTMLInputElement>(null);
  const [search, setSearch] = React.useState(filters.q);
  const [cursor, setCursor] = React.useState(0);

  React.useEffect(() => {
    const t = setTimeout(() => search !== filters.q && set({ q: search }), 250);
    return () => clearTimeout(t);
  }, [search, filters.q, set]);

  const q = useQuery({
    queryKey: ["leads", filters],
    queryFn: () => api.leads({ ...filters, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const rows = React.useMemo(() => q.data?.items ?? [], [q.data]);
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / PAGE_SIZE)) : 1;

  React.useEffect(() => setCursor(0), [q.data]);

  // Deep link: /leads?lead=LD-00123 opens that lead's drawer.
  const deepLink = useSearchParams().get("lead");
  React.useEffect(() => {
    if (deepLink) open(deepLink);
  }, [deepLink, open]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
      if (e.key === "/" && !typing) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === "Escape" && target === searchRef.current) {
        searchRef.current?.blur();
      } else if (!typing && !document.querySelector("[role=dialog]")) {
        if (e.key === "j") setCursor((c) => Math.min(c + 1, rows.length - 1));
        else if (e.key === "k") setCursor((c) => Math.max(c - 1, 0));
        else if (e.key === "Enter" && rows[cursor]) open(rows[cursor].lead_id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, cursor, open]);

  React.useEffect(() => {
    document.querySelector(`[data-row="${cursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  const columns = React.useMemo<ColumnDef<LeadRow>[]>(
    () => [
      {
        id: "name",
        header: "Lead",
        cell: ({ row: { original: l } }) => (
          <div className="min-w-0">
            <div className="truncate font-medium">
              {l.first_name} {l.last_name}
            </div>
            <div className="truncate text-2xs text-zinc-500">
              <span className="font-mono">{l.lead_id}</span> · {l.title?.trim() || "No title"}
            </div>
          </div>
        ),
      },
      {
        id: "company",
        header: "Company",
        cell: ({ row: { original: l } }) => (
          <div className="min-w-0">
            <div className="truncate text-zinc-800">{l.company}</div>
            <div className="truncate text-2xs text-zinc-500">
              {l.industry} · {fmt.int(l.employees)}
            </div>
          </div>
        ),
      },
      { id: "stage", header: "Stage", cell: ({ row }) => <StageBadge stage={row.original.stage} /> },
      { id: "owner", header: "Owner", cell: ({ row }) => <span className="text-zinc-700">{row.original.owner}</span> },
      {
        id: "last_contacted_at",
        header: "Last contact",
        cell: ({ row }) => {
          const d = asOf ? daysSince(asOf, row.original.last_contacted_at) : null;
          return (
            <span className="tnum font-mono text-xs text-zinc-600">
              {row.original.last_contacted_at ? (d != null ? `${d}d ago` : fmt.date(row.original.last_contacted_at)) : "never"}
            </span>
          );
        },
      },
      {
        id: "issues",
        header: "Issues",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.issues.map((i) => (
              <IssueBadge key={i} issue={i} />
            ))}
          </div>
        ),
      },
      {
        id: "fit",
        header: "F/I/R",
        enableSorting: false,
        cell: ({ row: { original: l } }) => (
          <span className="tnum whitespace-nowrap font-mono text-xs text-zinc-500">
            {l.fit.toFixed(0)}/{l.intent.toFixed(0)}/{l.recency.toFixed(0)}
          </span>
        ),
      },
      { id: "score", header: "Score", cell: ({ row }) => <ScoreCell score={row.original.score} /> },
    ],
    [asOf],
  );

  const sorting: SortingState = [{ id: filters.sort, desc: filters.order === "desc" }];
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    manualSorting: true,
    manualPagination: true,
    getCoreRowModel: getCoreRowModel(),
    onSortingChange: (updater) => {
      const next = typeof updater === "function" ? updater(sorting) : updater;
      const s = next[0];
      set(s ? { sort: s.id, order: s.desc ? "desc" : "asc" } : { sort: "", order: "" });
    },
  });

  const activeFilters = [filters.q, filters.stage, filters.owner, filters.industry, filters.issue].filter(Boolean).length;

  return (
    <>
      <PageHeader
        title="Leads"
        description={q.data ? `${fmt.int(q.data.total)} ${activeFilters ? "matching" : "total"}` : undefined}
        actions={
          <span className="hidden items-center gap-1.5 text-2xs text-zinc-500 md:flex">
            <Kbd>/</Kbd> search <Kbd>J</Kbd>
            <Kbd>K</Kbd> move <Kbd>↵</Kbd> open
          </span>
        }
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-zinc-200 px-6 py-2.5">
        <div className="relative w-64">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-zinc-400" />
          <Input
            ref={searchRef}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, company, ID"
            className="pl-8"
            aria-label="Search leads"
          />
        </div>
        <Select value={filters.stage} onChange={(e) => set({ stage: e.target.value })} aria-label="Stage">
          <option value="">All stages</option>
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
        <Select value={filters.owner} onChange={(e) => set({ owner: e.target.value })} aria-label="Owner">
          <option value="">All owners</option>
          {OWNERS.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </Select>
        <Select value={filters.industry} onChange={(e) => set({ industry: e.target.value })} aria-label="Industry">
          <option value="">All industries</option>
          {INDUSTRIES.map((i) => (
            <option key={i}>{i}</option>
          ))}
        </Select>
        <Select value={filters.issue} onChange={(e) => set({ issue: e.target.value })} aria-label="Data issues">
          <option value="">Any data quality</option>
          {ISSUES.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </Select>
        {activeFilters ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch("");
              set({ q: "", stage: "", owner: "", industry: "", issue: "" });
            }}
          >
            Clear
          </Button>
        ) : null}
      </div>

      {q.isError ? (
        <div className="p-6">
          <ErrorState error={q.error} onRetry={() => q.refetch()} />
        </div>
      ) : (
        <div className={cn("transition-opacity", q.isFetching && q.isPlaceholderData && "opacity-60")}>
          <table className="w-full table-fixed text-sm">
            <colgroup>
              <col className="w-[22%]" />
              <col className="w-[18%]" />
              <col className="w-[9%]" />
              <col className="w-[10%]" />
              <col className="w-[9%]" />
              <col className="w-[12%]" />
              <col className="w-[9%]" />
              <col className="w-[11%]" />
            </colgroup>
            <thead className="sticky top-12 z-10 bg-white">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id} className="border-b border-zinc-200 text-left text-xs text-zinc-500">
                  {hg.headers.map((h) => {
                    const sortable = h.column.getCanSort();
                    const dir = h.column.getIsSorted();
                    return (
                      <th key={h.id} className="px-3 py-2 font-normal first:pl-6">
                        {sortable ? (
                          <button
                            className="inline-flex items-center gap-1 hover:text-zinc-900"
                            onClick={h.column.getToggleSortingHandler()}
                          >
                            {flexRender(h.column.columnDef.header, h.getContext())}
                            {dir === "asc" ? <ArrowUp className="size-3" /> : dir === "desc" ? <ArrowDown className="size-3" /> : null}
                          </button>
                        ) : (
                          flexRender(h.column.columnDef.header, h.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody>
              {q.isLoading
                ? Array.from({ length: 12 }).map((_, i) => (
                    <tr key={i} className="border-b border-zinc-100">
                      {columns.map((_, j) => (
                        <td key={j} className="px-3 py-3 first:pl-6">
                          <Skeleton className="h-4" />
                        </td>
                      ))}
                    </tr>
                  ))
                : table.getRowModel().rows.map((row, i) => (
                    <tr
                      key={row.id}
                      data-row={i}
                      onClick={() => {
                        setCursor(i);
                        open(row.original.lead_id);
                      }}
                      className={cn(
                        "cursor-pointer border-b border-zinc-100 hover:bg-zinc-50",
                        i === cursor && "bg-zinc-50 shadow-[inset_2px_0_0_theme(colors.accent.DEFAULT)]",
                      )}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-3 py-2 align-middle first:pl-6">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  ))}
            </tbody>
          </table>
          {!q.isLoading && rows.length === 0 ? (
            <EmptyState title="No leads match these filters" hint="Try clearing a filter or searching for something broader." />
          ) : null}
          {q.data && q.data.total > 0 ? (
            <div className="flex items-center justify-between px-6 py-3 text-xs text-zinc-500">
              <span className="tnum">
                {fmt.int((filters.page - 1) * PAGE_SIZE + 1)}–{fmt.int(Math.min(filters.page * PAGE_SIZE, q.data.total))} of{" "}
                {fmt.int(q.data.total)}
              </span>
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" disabled={filters.page <= 1} onClick={() => set({ page: filters.page - 1 })} aria-label="Previous page">
                  <ChevronLeft />
                </Button>
                <span className="tnum px-1">
                  {filters.page} / {pages}
                </span>
                <Button size="icon" variant="ghost" disabled={filters.page >= pages} onClick={() => set({ page: filters.page + 1 })} aria-label="Next page">
                  <ChevronRight />
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}
