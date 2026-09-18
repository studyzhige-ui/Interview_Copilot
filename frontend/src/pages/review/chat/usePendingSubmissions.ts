import { useEffect, useState } from 'react';
import { listPendingSubmissions } from '@/api/chat';
import type { PendingSubmissionItem } from '@/types/api';

const REFRESH_MS = 3_000;

/** Poll the server-owned pending queue for the active conversation. */
export function usePendingSubmissions(
  sessionId: string | null,
  refreshToken: number,
): { items: PendingSubmissionItem[]; loaded: boolean; error: string | null } {
  const [projection, setProjection] = useState<{
    sessionId: string | null;
    items: PendingSubmissionItem[];
    loaded: boolean;
    error: string | null;
  }>({ sessionId: null, items: [], loaded: false, error: null });

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
        if (!controller.signal.aborted) setProjection({ sessionId, items, loaded: true, error: null });
      } catch (error) {
        if (!controller.signal.aborted && (error as { name?: string })?.name !== 'AbortError') {
          setProjection((previous) => ({
            sessionId,
            items: previous.sessionId === sessionId ? previous.items : [],
            loaded: previous.sessionId === sessionId && previous.loaded,
            error: '待发送消息暂时无法读取，显示的可能不是最新状态。',
          }));
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

  if (projection.sessionId !== sessionId) return { items: [], loaded: false, error: null };
  return { items: projection.items, loaded: projection.loaded, error: projection.error };
}
