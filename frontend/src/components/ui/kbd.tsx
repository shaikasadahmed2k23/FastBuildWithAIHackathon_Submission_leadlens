import type * as React from "react";

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-4 min-w-4 items-center justify-center rounded border border-zinc-200 bg-zinc-50 px-1 font-mono text-[10px] text-zinc-500">
      {children}
    </kbd>
  );
}
