"use client";

import { useCallback, useEffect, useState } from "react";
import {
  canUseTutorSpeech,
  speakTutorReply,
  stopTutorSpeech,
} from "@/lib/speech/tutorSpeech";

export function useTutorSpeech() {
  const [isSupported, setIsSupported] = useState(true);

  useEffect(() => {
    setIsSupported(canUseTutorSpeech());
  }, []);

  const speak = useCallback((text: string) => {
    if (!canUseTutorSpeech()) {
      setIsSupported(false);
      return;
    }

    speakTutorReply(text);
  }, []);

  const stop = useCallback(() => {
    stopTutorSpeech();
  }, []);

  return {
    isSupported,
    speak,
    stop,
  };
}
