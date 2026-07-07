export const DEFAULT_AUDIO_MIME_TYPE = "audio/webm";
export const DEFAULT_AUDIO_FILENAME = "recording.webm";

export function chooseSupportedMimeType(): string {
  if (typeof MediaRecorder === "undefined") {
    return DEFAULT_AUDIO_MIME_TYPE;
  }

  if (MediaRecorder.isTypeSupported(DEFAULT_AUDIO_MIME_TYPE)) {
    return DEFAULT_AUDIO_MIME_TYPE;
  }

  return "";
}

export function stopStreamTracks(stream: MediaStream | null): void {
  stream?.getTracks().forEach((track) => track.stop());
}
