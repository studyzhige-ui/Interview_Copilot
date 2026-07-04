import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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

// One in-flight auto-create per interview, shared across component
// instances. StrictMode's dev double-mount re-runs the auto-create
// effect on a fresh ref before the first create resolves — without
// this, a brand-new record would get TWO "会话 1" rows. (The pre-React-
// Query code avoided that by aborting the first mount's list fetch
// before it reached the create branch.) Entries clear on settle, so a
// later revisit can auto-create again — same as the old behavior.
const inflightAutoCreate = new Map<string, ReturnType<typeof createChatSession>>();

/**
 * Internal-mode session list: load + auto-pick + auto-create + CRUD.
 *
 * Only active when the caller passes ``interviewId`` (review/debrief
 * mode); in external mode the parent owns the list and this hook stays
 * inert.
 *
 * The list itself is a React Query entry keyed
 * ``['chat','sessions',{type,subject_id}]`` — same key family as the
 * general-chat sidebar — so switching interview A → B → A serves A's
 * list from cache instantly, and the query-level abort covers the
 * fetch race the old AbortController handled by hand. Creates /
 * renames / deletes update the cached list in place.
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
  const [internalActiveId, setInternalActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);

  const enabled = !externalMode && !!interviewId;
  const queryKey = ['chat', 'sessions', { type: sessionType, subject_id: interviewId ?? '' }];

  const listQuery = useQuery({
    queryKey,
    enabled,
    // listChatSessions returns updated_at DESC — first row is the most
    // recently active session, which is the right default selection.
    queryFn: ({ signal }) => listChatSessions(
      { type: sessionType, subject_id: interviewId! },
      { signal },
    ),
  });
  useToastOnError(listQuery.error, '会话列表加载失败');
  const sessions = (enabled ? listQuery.data : undefined) ?? [];

  const setSessions = useCallback(
    (updater: (cur: ChatSessionListItem[]) => ChatSessionListItem[]) => {
      queryClient.setQueryData<ChatSessionListItem[]>(
        ['chat', 'sessions', { type: sessionType, subject_id: interviewId ?? '' }],
        (cur) => updater(cur ?? []),
      );
    },
    [queryClient, sessionType, interviewId],
  );

  // ── Auto-pick + auto-create ───────────────────────────────────────────
  // Auto-create "会话 1" so the panel isn't a blank slate when the user
  // clicks into a fresh record — but only ONCE per interviewId. The guard
  // ref covers two hazards the old load-effect handled implicitly:
  //  * StrictMode / remount double-fire would create two sessions;
  //  * the user deleting the list down to zero must NOT resurrect it
  //    (the old effect only ran on interviewId change, so an emptied
  //    list stayed empty — we keep that contract).
  const autoCreatedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!enabled || !interviewId) {
      setInternalActiveId(null);
      return;
    }
    if (!listQuery.isSuccess) return;
    const rows = listQuery.data;
    if (rows.length > 0) {
      // Keep the current selection when it's still in the list (a cache
      // refresh must not yank the user off their session); otherwise
      // default to the most recent row.
      setInternalActiveId((cur) =>
        cur && rows.some((r) => r.session_id === cur) ? cur : rows[0].session_id,
      );
      return;
    }
    if (autoCreatedForRef.current === interviewId) {
      // List emptied after the one-shot auto-create (user deleted down
      // to zero) — release the selection instead of pointing at a dead id.
      setInternalActiveId(null);
      return;
    }
    autoCreatedForRef.current = interviewId;
    (async () => {
      try {
        let pending = inflightAutoCreate.get(interviewId);
        if (!pending) {
          pending = createChatSession({
            type: sessionType,
            subject_id: interviewId,
            title: '会话 1',
          }).finally(() => { inflightAutoCreate.delete(interviewId); });
          inflightAutoCreate.set(interviewId, pending);
        }
        const created = await pending;
        setSessions(() => [{
          session_id: created.session_id,
          title: created.title,
          type: created.type,
          state_summary: '',
          turn_count: 0,
          updated_at: new Date().toISOString(),
        }]);
        setInternalActiveId(created.session_id);
      } catch (e) {
        toast.error(extractErr(e, '会话列表加载失败'));
      }
    })();
  }, [enabled, interviewId, sessionType, listQuery.isSuccess, listQuery.data, setSessions]);

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
      setSessions((s) => [{
        session_id: created.session_id,
        title: created.title,
        type: created.type,
        state_summary: '',
        turn_count: 0,
        updated_at: new Date().toISOString(),
      }, ...s]);
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
      // Selection fallback (next row / null) is handled by the auto-pick
      // effect once the cached list no longer contains the active id.
      setSessions((s) => s.filter((x) => x.session_id !== id));
      setPendingDelete(null);
    } catch (e) { toast.error(extractErr(e, '删除会话失败')); }
    finally { setDeletingChat(false); }
  }, [pendingDelete, onSessionDeleted, setSessions]);

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
