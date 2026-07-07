import Image from "next/image";
import { Card } from "@/components/ui/Card";
import { formatSeverity } from "@/lib/format/scores";
import {
  formatWeaknessCategory,
  formatWeaknessStatus,
  getMemoryMoment,
} from "@/lib/format/memory";
import type { MemoryResponse } from "@/types/api";

export function MemoryMomentCard({
  before,
  after,
}: {
  before: MemoryResponse;
  after: MemoryResponse;
}) {
  const moment = getMemoryMoment(before, after);

  if (moment.type === "none") {
    return (
      <Card className="border-jade/20 bg-jade/5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <Image
            alt="Jade memory pearl"
            className="h-16 w-16 shrink-0"
            height={64}
            src="/mascot/memory-pearl.svg"
            width={64}
          />
          <div>
            <p className="text-xs font-semibold uppercase text-jade">
              Memory Moment
            </p>
            <h2 className="mt-2 text-xl font-semibold text-ink">{moment.title}</h2>
            <p className="mt-2 text-sm leading-6 text-ink/70">
              No repeated weakness detected yet. Try another speaking session with the same
              learner ID.
            </p>
          </div>
        </div>
      </Card>
    );
  }

  const afterWeakness = moment.after;

  return (
    <Card className="border-jade/25 bg-gradient-to-br from-white to-jade/10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <Image
          alt="Jade memory pearl"
          className="h-16 w-16 shrink-0"
          height={64}
          src="/mascot/memory-pearl.svg"
          width={64}
        />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase text-jade">
            Memory Moment
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-ink">{moment.title}</h2>
          <p className="mt-1 text-sm text-ink/60">
            {formatWeaknessCategory(afterWeakness.weakness_category)}
          </p>

          <dl className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <dt className="text-sm text-ink/55">Weakness</dt>
              <dd className="mt-1 font-semibold text-ink">{afterWeakness.weakness_name}</dd>
            </div>
            <div>
              <dt className="text-sm text-ink/55">Times failed</dt>
              <dd className="mt-1 font-semibold text-ink">
                {moment.before ? `${moment.before.times_failed} -> ` : "New -> "}
                {afterWeakness.times_failed}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-ink/55">Status</dt>
              <dd className="mt-1 font-semibold text-ink">
                {formatWeaknessStatus(afterWeakness.status)}
              </dd>
            </div>
            <div>
              <dt className="text-sm text-ink/55">Severity score</dt>
              <dd className="mt-1 font-semibold text-ink">
                {formatSeverity(afterWeakness.severity_score)}
              </dd>
            </div>
          </dl>

          <div className="mt-5 rounded-md border border-jade/20 bg-white p-4">
            <p className="text-sm font-semibold text-ink">Next drill</p>
            <p className="mt-2 text-sm leading-6 text-ink/75">
              {afterWeakness.recommended_drill}
            </p>
          </div>
        </div>
      </div>
    </Card>
  );
}
