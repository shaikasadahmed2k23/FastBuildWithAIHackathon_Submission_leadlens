import { AlertCircle } from "lucide-react";
import type * as React from "react";

import { Button } from "@/components/ui/button";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="flex flex-col items-start gap-3 border-l-2 border-alert bg-panel py-3 pl-4 pr-3">
      <div className="flex items-start gap-2 text-sm text-ink">
        <AlertCircle className="mt-0.5 size-4 shrink-0 text-alert" />
        <div>
          <p className="font-medium">Couldn&apos;t load this</p>
          <p className="text-ink-600">{message}</p>
        </div>
      </div>
      {onRetry ? (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-4 py-14 text-center">
      <p className="font-serif text-base italic text-ink">{title}</p>
      {hint ? <p className="max-w-sm text-sm text-ink-500">{hint}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
