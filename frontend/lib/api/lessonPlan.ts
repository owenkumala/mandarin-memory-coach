import { apiFetch } from "./client";
import type { LessonPlanResponse } from "@/types/api";

export async function getLessonPlan(userId: string): Promise<LessonPlanResponse> {
  return apiFetch<LessonPlanResponse>(`/lesson-plan/${encodeURIComponent(userId)}`);
}
