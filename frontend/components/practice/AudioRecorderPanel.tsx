import { Button } from "@/components/ui/Button";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { RecordButton } from "./RecordButton";
import type { RecordingState } from "@/hooks/useAudioRecorder";

export function AudioRecorderPanel({
  audioBlob,
  error,
  isUploading,
  onFileSelected,
  onReset,
  onStart,
  onStop,
  onSubmit,
  recordingState,
}: {
  audioBlob: Blob | null;
  error: string | null;
  isUploading: boolean;
  onFileSelected: (file: File) => void;
  onReset: () => void;
  onStart: () => void;
  onStop: () => void;
  onSubmit: () => void;
  recordingState: RecordingState;
}) {
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <RecordButton recordingState={recordingState} onStart={onStart} onStop={onStop} />
        <Button
          disabled={!audioBlob || isUploading}
          onClick={onSubmit}
          type="button"
          variant="secondary"
        >
          {isUploading ? "Uploading to tutor..." : "Send to tutor"}
        </Button>
        <Button onClick={onReset} type="button" variant="secondary">
          Reset
        </Button>
      </div>

      <label className="grid gap-2 text-sm font-medium text-ink">
        Upload audio instead
        <input
          accept=".webm,.wav,.mp3,.m4a,audio/webm,audio/wav,audio/mpeg,audio/mp4"
          className="rounded-md border border-dashed border-ink/20 bg-white p-3 text-sm"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              onFileSelected(file);
            }
          }}
          type="file"
        />
      </label>

      <p aria-live="polite" className="text-sm text-ink/65">
        State: <span className="font-semibold text-ink">{recordingState}</span>
        {audioBlob ? `, audio ready (${Math.round(audioBlob.size / 1024)} KB)` : ""}
      </p>

      {error ? <ErrorMessage message={error} /> : null}
    </div>
  );
}
