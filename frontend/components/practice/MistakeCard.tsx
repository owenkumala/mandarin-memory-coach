import { Badge } from "@/components/ui/Badge";
import { formatWeaknessCategory } from "@/lib/format/memory";
import type { MistakeAnalysis } from "@/types/api";

export function MistakeCard({ mistake }: { mistake: MistakeAnalysis }) {
  return (
    <article className="rounded-md border border-ink/10 bg-porcelain p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">{mistake.target}</h3>
          <p className="mt-1 text-xs text-ink/55">
            {mistake.type} · {formatWeaknessCategory(mistake.weakness_category)}
          </p>
        </div>
        <Badge tone={mistake.severity >= 4 ? "active" : "improving"}>
          Severity {mistake.severity}
        </Badge>
      </div>
      <p className="mt-4 text-sm leading-6 text-ink/75">{mistake.feedback}</p>
      <p className="mt-3 rounded-md bg-white px-3 py-2 text-sm text-ink/70">
        {mistake.example_sentence}
      </p>
      <p className="mt-3 text-sm font-medium text-ink">{mistake.recommended_drill}</p>
    </article>
  );
}
