import { useCallback, useEffect, useMemo, useState } from 'react';
import { CancelledError, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import { useToastOnError } from '@/hooks/useToastOnError';
import type { ChatSessionListItem } from '@/types/api';
import { clearPersistedSessionState } from './usePersistedSessionState';

function toListItem(created: { session_id: string; title: string; type: string }): ChatSessionListItem {
  return {
    session_id: created.session_id,
    title: created.title,
    type: created.type,
    state_summary: '',
    turn_count: 0,
    updated_at: new Date().toISOString(),
  };
}

/**
 * Internal-mode session list: load + auto-pick + auto-create + CRUD.
 *
 * Only active when the caller passes ``interviewId`` (review/debrief
 * mode); in external mode the parent owns the list and this hook stays
 * inert.
 *
 * The list is a React Query entry keyed
 * ``['chat','sessions',{type,subject_id}]`` — same key family as the
 * general-chat sidebar — so revisiting a record serves its list from
 * cache instantly. Creates / renames / deletes update the cached list
 * in place.
 */
export function useSessionList({
  externalMode,
  interviewId,
  sessionType,
  onSessionDeleted,
}: {
  externalMode: boolean;
  interviewId: string | null | undefined;
  sessionType: 'debrief' | 'general';
  /** Cleanup callback (drop SSE runtime etc.) when a session is deleted. */
  onSessionDeleted: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [selectedId, setInternalActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);

  const enabled = !externalMode && !!interviewId;
  const listQuery = useQuery({
    queryKey: ['chat', 'sessions', { type: sessionType, subject_id: interviewId ?? '' }],
    enabled,
    queryFn: ({ signal }) => listChatSessions(
      { type: sessionType, subject_id: interviewId! },
      { signal },
    ),
  });
  useToastOnError(listQuery.error, '会话列表加载失败');
  const sessions = useMemo(
    () => (enabled ? listQuery.data : undefined) ?? [],
    [enabled, listQuery.data],
  );
  const internalActiveId = enabled ? selectedId : null;

  const setSessions = useCallback(
    (updater: (cur: ChatSessionListItem[]) => ChatSessionListItem[]) => {
      const key = ['chat', 'sessions', { type: sessionType, subject_id: interviewId ?? '' }];
      // Cancel any in-flight background refetch first — otherwise its
      // (pre-mutation) response could land after this write and undo it.
      void queryClient.cancelQueries({ queryKey: key });
      queryClient.setQueryData<ChatSessionListItem[]>(key, (cur) => updater(cur ?? []));
    },
    [queryClient, sessionType, interviewId],
  );

  // ── Once per visit: load, pick the most recent, auto-create if empty ──
  // Same shape as before the React Query migration: this effect runs on
  // interviewId change only, so later cache updates (e.g. the user
  // deleting the list down to zero) can never re-trigger the
  // auto-create. ``ensureQueryData`` serves the cached list instantly on
  // revisit, fetches otherwise, and dedupes concurrent calls — which
  // also makes StrictMode's dev double-mount create at most one session
  // (the first run's ``alive`` flag drops before it reaches the create).
  useEffect(() => {
    if (!enabled || !interviewId) {
      return;
    }
    const key = ['chat', 'sessions', { type: sessionType, subject_id: interviewId }];
    let alive = true;
    (async () => {
      try {
        const rows = await queryClient.ensureQueryData({
          queryKey: key,
          queryFn: ({ signal }) => listChatSessions(
            { type: sessionType, subject_id: interviewId },
            { signal },
          ),
        });
        if (!alive) return;
        if (rows.length > 0) {
          // updated_at DESC — first row is the most recently active
          // session, the right default per the product spec.
          setInternalActiveId(rows[0].session_id);
          return;
        }
        // No sessions yet → auto-create "会话 1" so the panel isn't a
        // blank slate on a fresh record. The user can still delete this
        // down to zero if they don't want it.
        const created = await createChatSession({
          type: sessionType,
          subject_id: interviewId,
          title: '会话 1',
        });
        // The cache write is keyed to THIS record — do it even if the
        // user has switched away, so the session that now exists on the
        // backend isn't hidden behind a stale-empty cache entry.
        queryClient.setQueryData<ChatSessionListItem[]>(key, [toListItem(created)]);
        if (!alive) return;
        setInternalActiveId(created.session_id);
      } catch (e) {
        if (!alive) return;
        if (e instanceof CancelledError) return;                 // query cancelled
        if ((e as { code?: string })?.code === 'ERR_CANCELED') return;  // axios abort
        toast.error(extractErr(e, '会话列表加载失败'));
      }
    })();
    return () => { alive = false; };
  }, [enabled, interviewId, sessionType, queryClient]);

  // ── Create ────────────────────────────────────────────────────────────
  const newChat = useCallback(async () => {
    if (externalMode || !interviewId || creating) return;
    setCreating(true);
    try {
      const created = await createChatSession({
        type: sessionType,
        subject_id: interviewId,
        title: `会话 ${sessions.length + 1}`,
      });
      setSessions((s) => [toListItem(created), ...s]);
      setInternalActiveId(created.session_id);
    } catch (e) {
      toast.error(extractErr(e, '创建会话失败'));
    } finally { setCreating(false); }
  }, [externalMode, interviewId, sessionType, creating, sessions.length, setSessions]);

  // ── Delete (confirm-dialog flow) ──────────────────────────────────────
  // We render a styled <ConfirmDialog> instead of the unstyled native
  // window.confirm (which shows up as a "Code" titled OS dialog — looks
  // like a Chrome extension popup and feels off-brand). ``pendingDelete``
  // carries both id and title so the dialog body can name the session.
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);

  const removeChat = useCallback((id: string) => {
    if (externalMode) return;
    const s = sessions.find((x) => x.session_id === id);
    setPendingDelete({ id, title: s?.title ?? '该会话' });
  }, [externalMode, sessions]);

  const confirmRemoveChat = useCallback(async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setDeletingChat(true);
    try {
      await deleteChatSession(id);
      onSessionDeleted(id);
      clearPersistedSessionState(id);
      const next = sessions.filter((x) => x.session_id !== id);
      setSessions(() => next);
      if (internalActiveId === id) setInternalActiveId(next[0]?.session_id ?? null);
      setPendingDelete(null);
    } catch (e) { toast.error(extractErr(e, '删除会话失败')); }
    finally { setDeletingChat(false); }
  }, [pendingDelete, sessions, internalActiveId, onSessionDeleted, setSessions]);

  // ── Rename ────────────────────────────────────────────────────────────
  const commitRename = useCallback(async () => {
    if (!renaming) return;
    const title = renaming.title.trim();
    if (!title) { setRenaming(null); return; }
    try {
      await renameChatSession(renaming.id, title);
      setSessions((s) => s.map((x) => x.session_id === renaming.id ? { ...x, title } : x));
    } catch (e) { toast.error(extractErr(e, '重命名失败')); }
    setRenaming(null);
  }, [renaming, setSessions]);

  return {
    sessions,
    internalActiveId,
    setInternalActiveId,
    creating,
    newChat,
    renaming,
    setRenaming,
    commitRename,
    pendingDelete,
    setPendingDelete,
    deletingChat,
    removeChat,
    confirmRemoveChat,
  };
}
