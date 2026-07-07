import type { LessonPlanResponse } from "@/types/api";

export function NextLessonCard({
  lessonPlan,
}: {
  lessonPlan: LessonPlanResponse | null;
}) {
  if (!lessonPlan) {
    return (
      <p className="rounded-md border border-dashed border-ink/15 p-4 text-sm text-ink/60">
        No lesson plan yet.
      </p>
    );
  }

  return (
    <div className="rounded-md border border-ink/10 bg-white p-4">
      <dl className="grid gap-3 text-sm">
        <div>
          <dt className="text-ink/55">Focus area</dt>
          <dd className="font-semibold text-ink">{lessonPlan.focus_area}</dd>
        </div>
        <div>
          <dt className="text-ink/55">Next scenario</dt>
          <dd className="font-semibold text-ink">{lessonPlan.next_scenario}</dd>
        </div>
        <div>
          <dt className="text-ink/55">Recommended drill</dt>
          <dd className="leading-6 text-ink/75">{lessonPlan.recommended_drill}</dd>
        </div>
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        {lessonPlan.target_words.map((word) => (
          <span
            className="rounded-md bg-saffron/10 px-2.5 py-1 text-xs font-semibold text-saffron"
            key={word}
          >
            {word}
          </span>
        ))}
      </div>
    </div>
  );
}
