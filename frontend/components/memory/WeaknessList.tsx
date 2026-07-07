import { WeaknessCard } from "./WeaknessCard";
import type { ActiveWeaknessResponse } from "@/types/api";

export function WeaknessList({
  weaknesses,
}: {
  weaknesses: ActiveWeaknessResponse[];
}) {
  if (weaknesses.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ink/15 p-4 text-sm text-ink/60">
        No weaknesses yet. Complete a speaking practice session first.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      {weaknesses.map((weakness) => (
        <WeaknessCard
          key={`${weakness.weakness_category}-${weakness.last_seen}`}
          weakness={weakness}
        />
      ))}
    </div>
  );
}
