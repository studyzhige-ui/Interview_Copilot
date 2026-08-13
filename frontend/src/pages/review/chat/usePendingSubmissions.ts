import { useEffect, useState } from 'react';
import { listPendingSubmissions } from '@/api/chat';
import type { PendingSubmissionItem } from '@/types/api';

const REFRESH_MS = 3_000;

/** Poll the server-owned pending queue for the active conversation. */
export function usePendingSubmissions(
  sessionId: string | null,
  refreshToken: number,
): { items: PendingSubmissionItem[]; loaded: boolean } {
  const [projection, setProjection] = useState<{
    sessionId: string | null;
    items: PendingSubmissionItem[];
    loaded: boolean;
  }>({ sessionId: null, items: [], loaded: false });

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    let loading = false;

    const refresh = async () => {
      if (loading) return;
      loading = true;
      try {
        const items = await listPendingSubmissions(sessionId, {
          signal: controller.signal,
        });
        setProjection({ sessionId, items, loaded: true });
      } catch (error) {
        if ((error as { name?: string })?.name !== 'AbortError') {
          // The queue is auxiliary projection UI. Keep its last good value;
          // send/stream errors are surfaced by their own request paths.
        }
      } finally {
        loading = false;
      }
    };

    void refresh();
    const timerId = window.setInterval(() => { void refresh(); }, REFRESH_MS);
    return () => {
      controller.abort();
      window.clearInterval(timerId);
    };
  }, [sessionId, refreshToken]);

  if (projection.sessionId !== sessionId) return { items: [], loaded: false };
  return { items: projection.items, loaded: projection.loaded };
}
