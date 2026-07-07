"use client";

import { useCallback, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { sendVoiceChat } from "@/lib/api/voiceChat";
import type { VoiceChatResponse } from "@/types/api";

export function useVoiceChat() {
  const [data, setData] = useState<VoiceChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const submitVoiceChat = useCallback(
    async (input: {
      audio: Blob;
      filename: string;
      userId: string;
      scenario: string;
      level: string;
    }) => {
      setIsUploading(true);
      setError(null);

      try {
        const response = await sendVoiceChat(input);
        setData(response);
        return response;
      } catch (caughtError) {
        const message =
          caughtError instanceof ApiError
            ? caughtError.message
            : "Could not reach the tutor. Please check that the backend is running.";
        setError(message);
        return null;
      } finally {
        setIsUploading(false);
      }
    },
    [],
  );

  return {
    data,
    error,
    isUploading,
    submitVoiceChat,
  };
}
