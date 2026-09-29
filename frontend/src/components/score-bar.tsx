import { cn } from "@/lib/utils";

/** Ten tick marks, filled in ink up to value/max (rounded to the nearest tick). */
export function Ticks({ value, max = 100, className }: { value: number; max?: number; className?: string }) {
  const filled = Math.round(Math.max(0, Math.min(1, value / max)) * 10);
  return (
    <span aria-hidden className={cn("inline-flex h-2.5 shrink-0 items-end gap-[3px]", className)}>
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} className={cn("h-full w-px", i < filled ? "bg-ink" : "bg-ink-300")} />
      ))}
    </span>
  );
}

export function ScoreCell({ score, className }: { score: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)} title={`Score ${score.toFixed(1)} of 100`}>
      <span className="tnum w-9 text-right font-mono text-xs text-ink">{score.toFixed(1)}</span>
      <Ticks value={score} />
    </span>
  );
}
