"use client";

import { useCallback, useRef, useState } from "react";
import {
  chooseSupportedMimeType,
  DEFAULT_AUDIO_FILENAME,
  DEFAULT_AUDIO_MIME_TYPE,
  stopStreamTracks,
} from "@/lib/audio/recorder";

export type RecordingState =
  | "idle"
  | "requesting_permission"
  | "recording"
  | "stopped"
  | "uploading"
  | "success"
  | "error";

export function useAudioRecorder() {
  const [recordingState, setRecordingState] = useState<RecordingState>("idle");
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const startRecording = useCallback(async () => {
    if (recordingState === "recording" || recordingState === "requesting_permission") {
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setError("This browser does not support microphone recording.");
      setRecordingState("error");
      return;
    }

    setError(null);
    setAudioBlob(null);
    setRecordingState("requesting_permission");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = chooseSupportedMimeType();
      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );

      chunksRef.current = [];
      streamRef.current = stream;
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, {
          type: mimeType || DEFAULT_AUDIO_MIME_TYPE,
        });
        setAudioBlob(blob);
        setRecordingState("stopped");
        stopStreamTracks(streamRef.current);
        streamRef.current = null;
        mediaRecorderRef.current = null;
      };

      recorder.start();
      setRecordingState("recording");
    } catch {
      stopStreamTracks(streamRef.current);
      streamRef.current = null;
      mediaRecorderRef.current = null;
      setError("Microphone access was blocked. Please allow microphone permission and try again.");
      setRecordingState("error");
    }
  }, [recordingState]);

  const stopRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
      return;
    }

    stopStreamTracks(streamRef.current);
    streamRef.current = null;
  }, []);

  const resetRecording = useCallback(() => {
    stopStreamTracks(streamRef.current);
    streamRef.current = null;
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    setAudioBlob(null);
    setError(null);
    setRecordingState("idle");
  }, []);

  return {
    audioBlob,
    audioFilename: DEFAULT_AUDIO_FILENAME,
    error,
    recordingState,
    resetRecording,
    setAudioBlob,
    setRecordingState,
    startRecording,
    stopRecording,
  };
}
