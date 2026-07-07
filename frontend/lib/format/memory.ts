import type {
  ActiveWeaknessResponse,
  MemoryResponse,
  WeaknessCategory,
  WeaknessStatus,
} from "@/types/api";

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

export type MemoryMoment =
  | {
      type: "new";
      title: "New weakness detected";
      before: null;
      after: ActiveWeaknessResponse;
    }
  | {
      type: "repeated";
      title: "Repeated weakness detected";
      before: ActiveWeaknessResponse;
      after: ActiveWeaknessResponse;
    }
  | {
      type: "none";
      title: "No repeated weakness detected yet";
      before: null;
      after: null;
    };

function weaknessKey(weakness: ActiveWeaknessResponse): string {
  return `${weakness.weakness_category}:${weakness.weakness_name.toLowerCase()}`;
}

export function getMemoryMoment(before: MemoryResponse, after: MemoryResponse): MemoryMoment {
  const beforeByKey = new Map(
    before.active_weaknesses.map((weakness) => [weaknessKey(weakness), weakness]),
  );

  const repeatedWeakness = after.active_weaknesses
    .map((afterWeakness) => ({
      after: afterWeakness,
      before: beforeByKey.get(weaknessKey(afterWeakness)) ?? null,
    }))
    .filter(
      (change): change is {
        after: ActiveWeaknessResponse;
        before: ActiveWeaknessResponse;
      } =>
        change.before !== null &&
        change.after.times_failed > change.before.times_failed,
    )
    .sort(
      (left, right) =>
        right.after.times_failed -
        right.before.times_failed -
        (left.after.times_failed - left.before.times_failed),
    )[0];

  if (repeatedWeakness) {
    return {
      type: "repeated",
      title: "Repeated weakness detected",
      before: repeatedWeakness.before,
      after: repeatedWeakness.after,
    };
  }

  const newWeakness = after.active_weaknesses.find(
    (afterWeakness) => !beforeByKey.has(weaknessKey(afterWeakness)),
  );

  if (newWeakness) {
    return {
      type: "new",
      title: "New weakness detected",
      before: null,
      after: newWeakness,
    };
  }

  return {
    type: "none",
    title: "No repeated weakness detected yet",
    before: null,
    after: null,
  };
}
