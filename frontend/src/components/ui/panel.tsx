import type * as React from "react";

import { cn } from "@/lib/utils";

export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("rounded border border-zinc-200 bg-white", className)}>
      {title ? (
        <header className="flex h-10 items-center justify-between gap-2 border-b border-zinc-200 px-3">
          <h2 className="text-xs font-medium text-zinc-900">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
