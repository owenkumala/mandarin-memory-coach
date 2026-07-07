import { formatScore } from "@/lib/format/scores";

export function ScoreBar({ label, score }: { label: string; score: number }) {
  const boundedScore = Math.max(0, Math.min(100, score));

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm">
        <span className="font-medium text-ink/75">{label}</span>
        <span className="font-semibold text-ink">{formatScore(boundedScore)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink/10">
        <div
          className="h-full rounded-full bg-jade"
          style={{ width: `${boundedScore}%` }}
        />
      </div>
    </div>
  );
}
