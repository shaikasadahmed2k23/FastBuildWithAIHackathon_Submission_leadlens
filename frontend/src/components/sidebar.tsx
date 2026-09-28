"use client";

import { useQuery } from "@tanstack/react-query";
import { FlaskConical, Inbox, LayoutGrid, MessageSquareText, Users } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { api } from "@/lib/api";
import { cn, fmt } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutGrid },
  { href: "/leads", label: "Leads", icon: Users },
  { href: "/ask", label: "Ask", icon: MessageSquareText },
  { href: "/approvals", label: "Approvals", icon: Inbox },
  { href: "/evals", label: "Evals", icon: FlaskConical },
];

export function Sidebar() {
  const pathname = usePathname();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 60_000 });
  const pending = useQuery({ queryKey: ["actions", "pending"], queryFn: () => api.actions("pending") });

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[216px] flex-col border-r border-zinc-200 bg-zinc-50">
      <div className="flex h-12 items-center gap-2 border-b border-zinc-200 px-4">
        <div className="grid size-5 place-items-center rounded bg-zinc-900 font-mono text-[11px] font-semibold text-white">L</div>
        <span className="text-sm font-semibold tracking-tight">LeadLens</span>
      </div>
      <nav className="flex-1 space-y-px p-2">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          const count = href === "/approvals" ? pending.data?.length : undefined;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex h-8 items-center gap-2.5 rounded px-2 text-sm text-zinc-600 hover:bg-zinc-200/50 hover:text-zinc-900",
                active && "bg-white text-zinc-900 shadow-[0_0_0_1px_theme(colors.zinc.200)]",
              )}
            >
              <Icon className="size-4 shrink-0" strokeWidth={1.75} />
              {label}
              {count ? (
                <span className="tnum ml-auto rounded bg-zinc-200 px-1.5 font-mono text-2xs text-zinc-700">{count}</span>
              ) : null}
            </Link>
          );
        })}
      </nav>
      <div className="space-y-1 border-t border-zinc-200 px-4 py-3 text-2xs text-zinc-500">
        {health.isError ? (
          <div className="flex items-center gap-1.5 text-red-700">
            <span className="size-1.5 rounded-full bg-red-500" /> API unreachable
          </div>
        ) : health.data ? (
          <>
            <div className="flex items-center gap-1.5">
              <span className={cn("size-1.5 rounded-full", health.data.mode === "full" ? "bg-emerald-500" : "bg-amber-500")} />
              {health.data.mode === "full" ? `LLM: ${health.data.llm}` : "Offline mode (no LLM key)"}
            </div>
            <div>Data as of {fmt.date(health.data.as_of)}</div>
          </>
        ) : (
          <div>Connecting…</div>
        )}
      </div>
    </aside>
  );
}
