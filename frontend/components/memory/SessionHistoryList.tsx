import { formatDateTime } from "@/lib/format/dates";
import type { SessionSummaryResponse } from "@/types/api";

export function SessionHistoryList({
  sessions,
}: {
  sessions: SessionSummaryResponse[];
}) {
  if (sessions.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-ink/15 p-4 text-sm text-ink/60">
        No recent sessions yet.
      </p>
    );
  }

  return (
    <div className="grid gap-3">
      {sessions.map((session) => (
        <article className="rounded-md border border-ink/10 bg-white p-4" key={session.id}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-ink">{session.scenario}</h3>
            <time className="text-xs text-ink/50">{formatDateTime(session.created_at)}</time>
          </div>
          <p className="mt-2 text-sm text-ink/70">{session.transcript}</p>
          <p className="mt-2 text-xs text-ink/50">{session.summary}</p>
        </article>
      ))}
    </div>
  );
}
