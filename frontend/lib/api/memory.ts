import { apiFetch } from "./client";
import type { MemoryResponse } from "@/types/api";

export async function getMemory(userId: string): Promise<MemoryResponse> {
  return apiFetch<MemoryResponse>(`/memory/${encodeURIComponent(userId)}`);
}
