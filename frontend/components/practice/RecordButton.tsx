import { Button } from "@/components/ui/Button";
import type { RecordingState } from "@/hooks/useAudioRecorder";

export function RecordButton({
  recordingState,
  onStart,
  onStop,
}: {
  recordingState: RecordingState;
  onStart: () => void;
  onStop: () => void;
}) {
  if (recordingState === "recording") {
    return (
      <Button aria-label="Stop recording" onClick={onStop} type="button" variant="danger">
        Stop recording
      </Button>
    );
  }

  return (
    <Button
      aria-label="Start recording"
      disabled={recordingState === "requesting_permission"}
      onClick={onStart}
      type="button"
    >
      {recordingState === "requesting_permission" ? "Requesting microphone..." : "Start recording"}
    </Button>
  );
}
