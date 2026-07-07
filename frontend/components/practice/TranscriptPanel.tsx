import { Card } from "@/components/ui/Card";

export function TranscriptPanel({ transcript }: { transcript: string }) {
  return (
    <Card>
      <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Transcript</p>
      <p className="mt-3 text-2xl font-semibold leading-relaxed text-ink">{transcript}</p>
    </Card>
  );
}
