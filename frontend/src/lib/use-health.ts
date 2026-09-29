"use client";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";

// One policy for every /health observer: React Query applies the retry settings of whichever
// observer starts a fetch, so differing options would let a quick-failing caller cut the
// cold-start wait short.
export const HEALTH_RETRY_EVERY_MS = 3000;
export const HEALTH_MAX_RETRIES = 40; // ~2 minutes: a sleeping free-tier API takes ~30s to wake

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    retry: HEALTH_MAX_RETRIES,
    retryDelay: HEALTH_RETRY_EVERY_MS,
    refetchInterval: 30_000,
  });
}
