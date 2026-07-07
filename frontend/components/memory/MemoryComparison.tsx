import { Card } from "@/components/ui/Card";
import { getMemoryHeadline } from "@/lib/format/memory";
import { NextLessonCard } from "./NextLessonCard";
import { WeaknessList } from "./WeaknessList";
import type { MemoryResponse } from "@/types/api";

export function MemoryComparison({
  before,
  after,
}: {
  before: MemoryResponse;
  after: MemoryResponse;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Memory before</p>
        <h2 className="mt-2 text-lg font-semibold text-ink">{getMemoryHeadline(before)}</h2>
        <div className="mt-4">
          <WeaknessList weaknesses={before.active_weaknesses} />
        </div>
      </Card>
      <Card>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Memory after</p>
        <h2 className="mt-2 text-lg font-semibold text-ink">{getMemoryHeadline(after)}</h2>
        <div className="mt-4">
          <WeaknessList weaknesses={after.active_weaknesses} />
        </div>
        <div className="mt-5">
          <h3 className="mb-3 text-sm font-semibold text-ink">Latest lesson plan</h3>
          <NextLessonCard lessonPlan={after.latest_lesson_plan} />
        </div>
      </Card>
    </div>
  );
}
