"use client";

import { useCallback, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { getMemory } from "@/lib/api/memory";
import type { MemoryResponse } from "@/types/api";

export function useMemory() {
  const [data, setData] = useState<MemoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const loadMemory = useCallback(async (userId: string) => {
    setIsLoading(true);
    setError(null);

    try {
      const memory = await getMemory(userId);
      setData(memory);
      return memory;
    } catch (caughtError) {
      const message =
        caughtError instanceof ApiError
          ? caughtError.message
          : "Could not load memory. Please check that the backend is running.";
      setError(message);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  return {
    data,
    error,
    isLoading,
    loadMemory,
  };
}
