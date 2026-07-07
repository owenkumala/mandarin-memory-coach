import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export function TutorReplyPanel({
  isSpeechSupported,
  onReplay,
  onStop,
  reply,
}: {
  isSpeechSupported: boolean;
  onReplay: () => void;
  onStop: () => void;
  reply: string;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">Tutor reply</p>
        <div className="flex flex-wrap gap-2">
          <Button disabled={!isSpeechSupported} onClick={onReplay} type="button" variant="secondary">
            Replay tutor voice
          </Button>
          <Button disabled={!isSpeechSupported} onClick={onStop} type="button" variant="secondary">
            Stop voice
          </Button>
        </div>
      </div>
      <p className="mt-3 text-lg leading-8 text-ink">{reply}</p>
      {!isSpeechSupported ? (
        <p className="mt-3 text-sm text-ink/55">
          Browser voice playback is unavailable here, but the text reply is ready.
        </p>
      ) : null}
    </Card>
  );
}
