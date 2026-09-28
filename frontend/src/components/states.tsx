import { AlertCircle } from "lucide-react";
import type * as React from "react";

import { Button } from "@/components/ui/button";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="flex flex-col items-start gap-3 rounded border border-red-200 bg-red-50/50 p-4">
      <div className="flex items-start gap-2 text-sm text-red-800">
        <AlertCircle className="mt-0.5 size-4 shrink-0" />
        <div>
          <p className="font-medium">Couldn&apos;t load this</p>
          <p className="text-red-700/80">{message}</p>
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
    <div className="flex flex-col items-center justify-center gap-1 px-4 py-12 text-center">
      <p className="text-sm font-medium text-zinc-900">{title}</p>
      {hint ? <p className="max-w-sm text-sm text-zinc-500">{hint}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}
