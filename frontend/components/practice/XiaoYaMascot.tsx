import Image from "next/image";
import type { RecordingState } from "@/hooks/useAudioRecorder";

type MascotMood = "idle" | "listening" | "thinking" | "celebrating";

const mascotByMood: Record<
  MascotMood,
  {
    alt: string;
    helperText: string;
    src: string;
  }
> = {
  idle: {
    alt: "Xiao Ya, a friendly duck mascot, holding a memory pearl",
    helperText: "I'll remember your Mandarin patterns.",
    src: "/mascot/xiao-ya-idle.svg",
  },
  listening: {
    alt: "Xiao Ya, a friendly duck mascot, listening to Mandarin audio",
    helperText: "I'm listening to your Mandarin.",
    src: "/mascot/xiao-ya-listening.svg",
  },
  thinking: {
    alt: "Xiao Ya, a friendly duck mascot, thinking about pronunciation and memory",
    helperText: "Checking pronunciation, fluency, and memory...",
    src: "/mascot/xiao-ya-thinking.svg",
  },
  celebrating: {
    alt: "Xiao Ya, a friendly duck mascot, celebrating a memory update",
    helperText: "I remembered what changed for next time!",
    src: "/mascot/xiao-ya-celebrating.svg",
  },
};

export function getMascotMood({
  hasMemoryUpdate,
  isUploading,
  recordingState,
}: {
  hasMemoryUpdate: boolean;
  isUploading: boolean;
  recordingState: RecordingState;
}): MascotMood {
  if (recordingState === "recording") {
    return "listening";
  }

  if (
    isUploading ||
    recordingState === "uploading" ||
    recordingState === "requesting_permission"
  ) {
    return "thinking";
  }

  if (hasMemoryUpdate) {
    return "celebrating";
  }

  return "idle";
}

export function XiaoYaMascot({
  className = "",
  mood,
}: {
  className?: string;
  mood: MascotMood;
}) {
  const mascot = mascotByMood[mood];

  return (
    <div
      className={`flex items-center gap-4 rounded-lg border border-jade/15 bg-white p-4 shadow-soft ${className}`}
    >
      <Image
        alt={mascot.alt}
        className="h-28 w-28 shrink-0"
        height={112}
        src={mascot.src}
        width={112}
      />
      <div>
        <p className="text-xs font-semibold uppercase text-jade">Xiao Ya / 小鸭</p>
        <p className="mt-2 text-base font-semibold leading-6 text-ink">{mascot.helperText}</p>
      </div>
    </div>
  );
}
