import { cn } from "@/lib/utils";

/** Placeholder drawn as empty ruled lines; no shimmer. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("ruled min-h-4", className)} />;
}
