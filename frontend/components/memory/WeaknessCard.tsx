import { Badge } from "@/components/ui/Badge";
import { formatSeverity } from "@/lib/format/scores";
import { formatWeaknessCategory, formatWeaknessStatus } from "@/lib/format/memory";
import type { ActiveWeaknessResponse } from "@/types/api";

export function WeaknessCard({ weakness }: { weakness: ActiveWeaknessResponse }) {
  return (
    <article className="rounded-md border border-ink/10 bg-porcelain p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-ink">{weakness.weakness_name}</h3>
          <p className="mt-1 text-xs text-ink/55">
            {formatWeaknessCategory(weakness.weakness_category)}
          </p>
        </div>
        <Badge tone={weakness.status}>{formatWeaknessStatus(weakness.status)}</Badge>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-ink/55">Severity</dt>
          <dd className="font-semibold text-ink">{formatSeverity(weakness.severity_score)}</dd>
        </div>
        <div>
          <dt className="text-ink/55">Times failed</dt>
          <dd className="font-semibold text-ink">{weakness.times_failed}</dd>
        </div>
      </dl>
      <p className="mt-4 text-sm leading-6 text-ink/75">{weakness.recommended_drill}</p>
    </article>
  );
}
