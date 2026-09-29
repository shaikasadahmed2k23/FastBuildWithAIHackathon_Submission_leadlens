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
      <div className="flex min-h-screen items-center justify-center p-8">
        <div className="max-w-md space-y-3 border-t border-ink pt-4">
          <p className="font-serif text-2xl font-semibold">The API isn&apos;t responding</p>
          <p className="text-sm leading-6 text-ink-600">
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
  const ticks = 30;
  const filled = Math.min(ticks - 1, elapsed);
  return (
    <div className="fade-in flex min-h-screen items-center justify-center p-8" role="status" aria-live="polite">
      <div className="w-[360px] space-y-3 border-t border-ink pt-4">
        <p className="smallcaps text-xs font-semibold text-ink-500">Before the first call</p>
        <p className="font-serif text-2xl font-semibold">Waking up server (~30s)</p>
        <p className="text-sm leading-6 text-ink-600">
          The API runs on a free instance that sleeps when nobody is reading. The first page of the day takes about half
          a minute; everything after that is quick.
        </p>
        <div className="flex items-end justify-between pt-1" aria-hidden>
          {Array.from({ length: ticks }, (_, i) => (
            <span key={i} className={i < filled ? "h-3 w-px bg-ink" : "h-2 w-px bg-ink-300"} />
          ))}
        </div>
        <p className="tnum font-mono text-2xs text-ink-500">{elapsed}s elapsed</p>
      </div>
    </div>
  );
}
