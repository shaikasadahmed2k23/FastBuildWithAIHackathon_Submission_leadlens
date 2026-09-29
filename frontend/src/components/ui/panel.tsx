import type * as React from "react";

import { cn } from "@/lib/utils";

/** A ledger section: an ink rule on top, a small-caps heading, content on the paper. No box. */
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
    <section className={cn("border-t border-ink", className)}>
      {title ? (
        <header className="flex h-9 items-center justify-between gap-2 border-b border-rule">
          <h2 className="smallcaps text-sm font-semibold text-ink">{title}</h2>
          {actions}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}
