import type { MemoryResponse, WeaknessCategory, WeaknessStatus } from "@/types/api";

const WEAKNESS_LABELS: Record<WeaknessCategory, string> = {
  tone_accuracy: "Tone accuracy",
  zh_ch_confusion: "zh/ch pronunciation",
  sentence_length: "Complete sentence answers",
  vocabulary_recall: "Vocabulary recall",
  grammar_structure: "Grammar structure",
  hesitation: "Hesitation and pauses",
};

const STATUS_LABELS: Record<WeaknessStatus, string> = {
  active: "Active",
  improving: "Improving",
  resolved: "Resolved",
};

export function formatWeaknessCategory(category: WeaknessCategory): string {
  return WEAKNESS_LABELS[category];
}

export function formatWeaknessStatus(status: WeaknessStatus): string {
  return STATUS_LABELS[status];
}

export function getMemoryHeadline(memory: MemoryResponse): string {
  if (memory.active_weaknesses.length === 0) {
    return "No active weaknesses yet";
  }

  const topWeakness = memory.active_weaknesses[0];
  return `${topWeakness.weakness_name} (${topWeakness.times_failed}x)`;
}
