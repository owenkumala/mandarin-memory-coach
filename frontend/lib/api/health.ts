import { apiFetch } from "./client";
import type { HealthResponse } from "@/types/api";

export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}
