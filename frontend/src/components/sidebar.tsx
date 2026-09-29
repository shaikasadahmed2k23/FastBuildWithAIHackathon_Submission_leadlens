"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { ResetDemoButton } from "@/components/reset-demo";
import { api } from "@/lib/api";
import { useHealth } from "@/lib/use-health";
import { cn, fmt } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/leads", label: "Leads" },
  { href: "/ask", label: "Ask" },
  { href: "/approvals", label: "Approvals" },
  { href: "/evals", label: "Evals" },
];

export function Sidebar() {
  const pathname = usePathname();
  const health = useHealth();
  const pending = useQuery({ queryKey: ["actions", "pending"], queryFn: () => api.actions("pending") });

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[180px] flex-col border-r border-rule bg-paper">
      <div className="flex h-14 items-center border-b border-rule px-5">
        <span className="font-serif text-[21px] font-semibold leading-none tracking-tight">LeadLens</span>
      </div>
      <nav className="flex-1 space-y-0.5 py-4">
        {NAV.map(({ href, label }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          const count = href === "/approvals" ? pending.data?.length : undefined;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex h-8 items-center px-5 text-sm text-ink-500 hover:text-ink",
                active && "font-medium text-ink before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:bg-accent",
              )}
            >
              {label}
              {count ? <span className="tnum ml-auto font-mono text-2xs text-pending-ink">{count}</span> : null}
            </Link>
          );
        })}
      </nav>
      <div className="space-y-1 border-t border-rule px-5 py-3 text-2xs text-ink-500">
        {health.isError ? (
          <div className="flex items-center gap-1.5 text-alert">
            <span className="size-1.5 rounded-full bg-alert" /> API unreachable
          </div>
        ) : health.data ? (
          <>
            <div>Data as of {fmt.date(health.data.as_of)}</div>
            <ResetDemoButton />
          </>
        ) : (
          <div>Connecting…</div>
        )}
      </div>
    </aside>
  );
}
