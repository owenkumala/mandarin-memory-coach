export function canUseTutorSpeech(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export function speakTutorReply(text: string): void {
  if (!canUseTutorSpeech()) {
    return;
  }

  window.speechSynthesis.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  window.speechSynthesis.speak(utterance);
}

export function stopTutorSpeech(): void {
  if (!canUseTutorSpeech()) {
    return;
  }

  window.speechSynthesis.cancel();
}
