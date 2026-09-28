import { cn } from "@/lib/utils";

export function ScoreBar({ value, max = 100, className }: { value: number; max?: number; className?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className={cn("h-1 w-full overflow-hidden rounded-full bg-zinc-100", className)}>
      <div className="h-full rounded-full bg-zinc-800" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function ScoreCell({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="tnum w-8 text-right font-mono text-xs text-zinc-900">{score.toFixed(1)}</span>
      <ScoreBar value={score} className="w-14" />
    </div>
  );
}
