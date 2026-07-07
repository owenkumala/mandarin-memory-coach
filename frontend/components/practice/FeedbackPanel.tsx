import { Card } from "@/components/ui/Card";
import { ScoreBar } from "@/components/ui/ScoreBar";
import { MistakeCard } from "./MistakeCard";
import type { AnalysisResponse } from "@/types/api";

export function FeedbackPanel({ feedback }: { feedback: AnalysisResponse }) {
  return (
    <Card>
      <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Feedback</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <ScoreBar label="Fluency" score={feedback.fluency_score} />
        <ScoreBar label="Confidence" score={feedback.confidence_score} />
      </div>
      <p className="mt-5 leading-7 text-ink/75">{feedback.summary}</p>
      <dl className="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-ink/55">Next focus</dt>
          <dd className="mt-1 font-semibold text-ink">{feedback.next_focus}</dd>
        </div>
        <div>
          <dt className="text-sm text-ink/55">Next drill</dt>
          <dd className="mt-1 font-semibold text-ink">{feedback.next_drill}</dd>
        </div>
      </dl>
      <div className="mt-5 grid gap-3">
        {feedback.mistakes.length > 0 ? (
          feedback.mistakes.map((mistake) => (
            <MistakeCard
              key={`${mistake.type}-${mistake.weakness_category}-${mistake.target}`}
              mistake={mistake}
            />
          ))
        ) : (
          <p className="rounded-md border border-dashed border-ink/15 p-4 text-sm text-ink/60">
            No specific mistakes detected in this turn.
          </p>
        )}
      </div>
    </Card>
  );
}
