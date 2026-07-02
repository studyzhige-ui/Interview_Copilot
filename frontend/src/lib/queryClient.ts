import { QueryClient } from '@tanstack/react-query';

/**
 * Shared React Query client — the app's server-state cache.
 *
 * Defaults tuned for this app's traffic shape:
 * - staleTime 30s: list data (sessions, models, memory) tolerates short
 *   staleness; refetches collapse across components sharing a key.
 * - retry 1: the axios client already surfaces friendly errors; more
 *   retries would just delay the toast.
 * - refetchOnWindowFocus off: SSE streams + explicit invalidation drive
 *   freshness here, not tab focus.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
