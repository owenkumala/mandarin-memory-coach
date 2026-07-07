"use client";

import { FormEvent, useEffect, useState } from "react";
import { AudioRecorderPanel } from "./AudioRecorderPanel";
import { VoiceChatResult } from "./VoiceChatResult";
import { getMascotMood, XiaoYaMascot } from "./XiaoYaMascot";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ErrorMessage } from "@/components/ui/ErrorMessage";
import { LoadingState } from "@/components/ui/LoadingState";
import { useAudioRecorder } from "@/hooks/useAudioRecorder";
import { useTutorSpeech } from "@/hooks/useTutorSpeech";
import { useVoiceChat } from "@/hooks/useVoiceChat";
import { DEFAULT_AUDIO_FILENAME } from "@/lib/audio/recorder";

const DEFAULT_USER_ID = "demo-user-asr-test-2";
const DEFAULT_SCENARIO = "restaurant ordering";
const DEFAULT_LEVEL = "HSK1 beginner";

export function PracticeShell() {
  const [userId, setUserId] = useState(DEFAULT_USER_ID);
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [level, setLevel] = useState(DEFAULT_LEVEL);
  const [audioFilename, setAudioFilename] = useState(DEFAULT_AUDIO_FILENAME);
  const recorder = useAudioRecorder();
  const voiceChat = useVoiceChat();
  const { isSupported, speak, stop } = useTutorSpeech();
  const mascotMood = getMascotMood({
    hasMemoryUpdate: Boolean(voiceChat.data?.memory_updated),
    isUploading: voiceChat.isUploading,
    recordingState: recorder.recordingState,
  });

  useEffect(() => {
    if (voiceChat.data?.tutor_reply) {
      speak(voiceChat.data.tutor_reply);
    }
  }, [speak, voiceChat.data?.tutor_reply]);

  async function submitCurrentAudio() {
    if (!recorder.audioBlob) {
      return;
    }

    recorder.setRecordingState("uploading");
    const response = await voiceChat.submitVoiceChat({
      audio: recorder.audioBlob,
      filename: audioFilename,
      userId,
      scenario,
      level,
    });
    recorder.setRecordingState(response ? "success" : "error");
  }

  function handleSettingsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitCurrentAudio();
  }

  return (
    <div className="grid gap-6">
      <div className="grid gap-5 lg:grid-cols-2 lg:items-end">
        <div className="min-w-0">
          <p className="text-sm font-semibold uppercase text-jade">
            SpeakHan memory coach
          </p>
          <h1 className="mt-2 text-4xl font-semibold leading-tight text-ink">
            Xiao Ya listens, coaches, and remembers what changes.
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-ink/65">
            Record twice with the same learner ID to make recurring Mandarin patterns visible.
          </p>
          <div aria-live="polite" className="mt-5">
            <XiaoYaMascot mood={mascotMood} />
          </div>
        </div>
        <Card className="min-w-0 border-jade/15">
          <form className="grid gap-3" onSubmit={handleSettingsSubmit}>
            <div>
              <p className="text-xs font-semibold uppercase text-ink/45">
                Demo learner
              </p>
              <p className="mt-1 text-sm text-ink/65">
                Memory continuity depends on this same user ID across sessions.
              </p>
            </div>
            <label className="grid gap-2 text-sm font-medium text-ink">
              User ID
              <input
                className="min-h-11 rounded-md border border-ink/15 bg-white px-3 text-ink outline-none focus:border-jade"
                onChange={(event) => setUserId(event.target.value)}
                value={userId}
              />
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="grid gap-2 text-sm font-medium text-ink">
                Scenario
                <input
                  className="min-h-11 rounded-md border border-ink/15 bg-white px-3 text-ink outline-none focus:border-jade"
                  onChange={(event) => setScenario(event.target.value)}
                  value={scenario}
                />
              </label>
              <label className="grid gap-2 text-sm font-medium text-ink">
                Level
                <input
                  className="min-h-11 rounded-md border border-ink/15 bg-white px-3 text-ink outline-none focus:border-jade"
                  onChange={(event) => setLevel(event.target.value)}
                  value={level}
                />
              </label>
            </div>
            <Button disabled={!recorder.audioBlob || voiceChat.isUploading} type="submit">
              {voiceChat.isUploading ? "Analyzing audio..." : "Analyze current audio"}
            </Button>
          </form>
        </Card>
      </div>

      <Card className="border-jade/15">
        <h2 className="mb-4 text-xl font-semibold text-ink">Practice controls</h2>
        <AudioRecorderPanel
          audioBlob={recorder.audioBlob}
          error={recorder.error}
          isUploading={voiceChat.isUploading}
          onFileSelected={(file) => {
            recorder.setAudioBlob(file);
            recorder.setRecordingState("stopped");
            setAudioFilename(file.name);
          }}
          onReset={() => {
            recorder.resetRecording();
            setAudioFilename(DEFAULT_AUDIO_FILENAME);
            stop();
          }}
          onStart={recorder.startRecording}
          onStop={recorder.stopRecording}
          onSubmit={() => void submitCurrentAudio()}
          recordingState={recorder.recordingState}
        />
      </Card>

      {voiceChat.error ? <ErrorMessage message={voiceChat.error} /> : null}
      {voiceChat.isUploading ? (
        <LoadingState label="Uploading audio and waiting for Qwen..." />
      ) : null}

      {voiceChat.data ? (
        <VoiceChatResult
          isSpeechSupported={isSupported}
          onReplay={() => speak(voiceChat.data?.tutor_reply ?? "")}
          onStopSpeech={stop}
          response={voiceChat.data}
        />
      ) : null}
    </div>
  );
}
