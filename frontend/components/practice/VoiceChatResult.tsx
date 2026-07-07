import { MemoryMomentCard } from "@/components/memory/MemoryMomentCard";
import { MemoryComparison } from "@/components/memory/MemoryComparison";
import { FeedbackPanel } from "./FeedbackPanel";
import { TranscriptPanel } from "./TranscriptPanel";
import { TutorReplyPanel } from "./TutorReplyPanel";
import type { VoiceChatResponse } from "@/types/api";

export function VoiceChatResult({
  isSpeechSupported,
  onReplay,
  onStopSpeech,
  response,
}: {
  isSpeechSupported: boolean;
  onReplay: () => void;
  onStopSpeech: () => void;
  response: VoiceChatResponse;
}) {
  return (
    <div className="grid gap-5">
      <TranscriptPanel transcript={response.transcript} />
      <TutorReplyPanel
        isSpeechSupported={isSpeechSupported}
        onReplay={onReplay}
        onStop={onStopSpeech}
        reply={response.tutor_reply}
      />
      <FeedbackPanel feedback={response.feedback} />
      <MemoryMomentCard before={response.memory_before} after={response.memory_after} />
      <MemoryComparison before={response.memory_before} after={response.memory_after} />
    </div>
  );
}
