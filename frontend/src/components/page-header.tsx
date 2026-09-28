import type * as React from "react";

import { ModeIndicator } from "@/components/mode-indicator";

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="sticky top-0 z-20 flex h-12 items-center justify-between gap-4 border-b border-zinc-200 bg-white px-6">
      <div className="flex min-w-0 items-baseline gap-3">
        <h1 className="text-sm font-semibold">{title}</h1>
        {description ? <p className="truncate text-sm text-zinc-500">{description}</p> : null}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {actions}
        <ModeIndicator />
      </div>
    </header>
  );
}
