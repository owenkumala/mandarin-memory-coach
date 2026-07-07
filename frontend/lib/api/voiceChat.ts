import { apiFetch } from "./client";
import type { VoiceChatResponse } from "@/types/api";

export async function sendVoiceChat(input: {
  audio: Blob;
  filename: string;
  userId: string;
  scenario: string;
  level: string;
}): Promise<VoiceChatResponse> {
  const formData = new FormData();
  formData.append("audio", input.audio, input.filename);
  formData.append("user_id", input.userId);
  formData.append("scenario", input.scenario);
  formData.append("level", input.level);

  return apiFetch<VoiceChatResponse>("/voice-chat", {
    method: "POST",
    body: formData,
  });
}
