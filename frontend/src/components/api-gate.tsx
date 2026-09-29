"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { useHealth } from "@/lib/use-health";

const SHOW_AFTER_MS = 1500; // a warm API answers well before this; only cold starts see the screen

/**
 * Holds the page until the API answers. The API runs on a free host that sleeps when
 * idle, so the first request after a pause can take ~30s; say so instead of showing errors.
 */
export function ApiGate({ children }: { children: React.ReactNode }) {
  const started = React.useRef(Date.now());
  const [now, setNow] = React.useState(Date.now());
  const health = useHealth();
  const ready = health.data !== undefined;

  React.useEffect(() => {
    if (ready) return;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [ready]);

  if (ready) return <>{children}</>;
  const elapsed = Math.round((now - started.current) / 1000);

  if (health.isError) {
    return (
      <div className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-sm space-y-3 text-center">
          <p className="text-sm font-medium">The API isn&apos;t responding</p>
          <p className="text-sm text-zinc-500">
            Tried for {elapsed}s. It may still be starting, or the backend URL may be misconfigured.
          </p>
          <Button
            size="sm"
            onClick={() => {
              started.current = Date.now();
              health.refetch();
            }}
          >
            Try again
          </Button>
        </div>
      </div>
    );
  }
  if (now - started.current < SHOW_AFTER_MS) return null;
  return (
    <div className="flex min-h-screen items-center justify-center p-6" role="status" aria-live="polite">
      <div className="w-72 space-y-3 text-center">
        <p className="text-sm font-medium">Waking up server (~30s)</p>
        <p className="text-xs text-zinc-500">
          The API runs on a free instance that sleeps when idle. This happens once; everything is fast afterwards.
        </p>
        <div className="h-1 overflow-hidden rounded-full bg-zinc-100">
          <div
            className="h-full rounded-full bg-zinc-800 transition-[width] duration-500"
            style={{ width: `${Math.min(95, (elapsed / 30) * 100)}%` }}
          />
        </div>
        <p className="tnum font-mono text-2xs text-zinc-400">{elapsed}s</p>
      </div>
    </div>
  );
}
