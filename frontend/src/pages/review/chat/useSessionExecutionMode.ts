import { useCallback, useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { extractErr } from '@/api/client';
import {
  getChatSessionExecutionMode,
  updateChatSessionExecutionMode,
} from '@/api/chat';
import { toast } from '@/store/uiStore';
import type { ChatSessionListItem } from '@/types/api';

type ExecutionMode = 'standard' | 'auto';

function detailKey(sessionId: string | null) {
  return ['chat', 'session-execution-mode', sessionId ?? ''] as const;
}

/**
 * Server-authoritative Standard/Auto setting for one Conversation.
 *
 * The session-list projection is only initial paint data. Every mount/focus
 * rereads the owner-scoped detail endpoint, and PATCH uses its independent
 * version token. A conflict triggers an immediate reread so this device never
 * keeps a stale local preference as truth.
 */
export function useSessionExecutionMode(
  activeSessionId: string | null,
  initial?: { execution_mode: ExecutionMode; execution_mode_version: number },
) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!activeSessionId) return;
    // One-way migration cleanup.  The server detail projection is the only
    // owner; an old local value must not survive as a misleading second copy.
    try { localStorage.removeItem(`execution-mode:${activeSessionId}`); } catch { /* ignore */ }
  }, [activeSessionId]);
  const query = useQuery({
    queryKey: detailKey(activeSessionId),
    queryFn: ({ signal }) => getChatSessionExecutionMode(activeSessionId!, { signal }),
    enabled: Boolean(activeSessionId),
    initialData: initial && activeSessionId
      ? {
          session_id: activeSessionId,
          execution_mode: initial.execution_mode,
          version: initial.execution_mode_version,
        }
      : undefined,
    // Initial list data and a previously cached device read are projections,
    // not authority. Reread as soon as the active toolbar mounts.
    initialDataUpdatedAt: 0,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const mutation = useMutation({
    mutationFn: async (next: ExecutionMode) => {
      if (!activeSessionId || !query.data) throw new Error('执行模式尚未加载');
      return updateChatSessionExecutionMode(
        activeSessionId,
        next,
        query.data.version,
      );
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(detailKey(saved.session_id), saved);
      // Keep every cached session-list projection coherent without turning it
      // into a second source of truth.
      queryClient.setQueriesData<ChatSessionListItem[]>(
        { queryKey: ['chat', 'sessions'] },
        (rows) => rows?.map((row) => row.session_id === saved.session_id
          ? {
              ...row,
              execution_mode: saved.execution_mode,
              execution_mode_version: saved.version,
            }
          : row),
      );
    },
    onError: async (error: unknown) => {
      const status = (error as { response?: { status?: number } }).response?.status;
      if (status === 409 && activeSessionId) {
        await queryClient.fetchQuery({
          queryKey: detailKey(activeSessionId),
          queryFn: ({ signal }) => getChatSessionExecutionMode(activeSessionId, { signal }),
          staleTime: 0,
        });
        toast.info('执行模式已在另一设备更新，已同步最新设置');
        return;
      }
      toast.error(extractErr(error, '执行模式更新失败'));
    },
  });

  const setExecutionMode = useCallback(async (next: ExecutionMode) => {
    if (mutation.isPending || next === query.data?.execution_mode) return;
    try {
      await mutation.mutateAsync(next);
    } catch {
      // onError owns conflict reread and user-facing reporting.
    }
  }, [mutation, query.data?.execution_mode]);

  return {
    executionMode: query.data?.execution_mode ?? initial?.execution_mode ?? 'standard',
    setExecutionMode,
    isPending: query.isPending || query.isFetching || mutation.isPending,
  };
}
