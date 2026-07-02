import { useCallback, useEffect, useState } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import type { ChatSessionListItem } from '@/types/api';
import { clearPersistedSessionState } from './usePersistedSessionState';

/**
 * Internal-mode session list: load + auto-pick + auto-create + CRUD.
 *
 * Only active when the caller passes ``interviewId`` (review/debrief
 * mode); in external mode the parent owns the list and this hook stays
 * inert.
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
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [internalActiveId, setInternalActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);

  // ── Load + auto-pick + auto-create ────────────────────────────────────
  // (One round-trip per interviewId change; the auto-create branch only
  // fires when the result list is empty.)
  useEffect(() => {
    if (externalMode) return;
    if (!interviewId) {
      setSessions([]);
      setInternalActiveId(null);
      return;
    }
    // ``listChatSessions`` race is worse than the read-only sibling
    // effects: if the result is empty we auto-create "会话 1", which
    // is a SIDE EFFECT on the backend. A rapid switch from interview
    // A → B → A could in principle land an auto-created session
    // attached to interview A while the UI has moved on. ``alive``
    // gates the FE write but doesn't stop the backend create from
    // committing. ``controller.abort()`` cancels the in-flight list
    // call, which prevents reaching the create branch in the first
    // place.
    const controller = new AbortController();
    let alive = true;
    (async () => {
      try {
        const rows = await listChatSessions(
          { type: sessionType, subject_id: interviewId },
          { signal: controller.signal },
        );
        if (!alive) return;
        if (rows.length > 0) {
          setSessions(rows);
          // listChatSessions returns updated_at DESC — first row is the
          // most recently active session, which is the right default
          // selection per the product spec.
          setInternalActiveId(rows[0].session_id);
          return;
        }
        // No sessions yet → auto-create "会话 1" so the panel isn't a
        // blank slate when the user clicks into a fresh record. The user
        // can still delete this down to zero if they don't want it.
        // ``createChatSession`` does not take an AbortSignal — the
        // post is fast (~30ms) and idempotent enough at this scope.
        const created = await createChatSession({
          type: sessionType,
          subject_id: interviewId,
          title: '会话 1',
        });
        if (!alive) return;
        setSessions([{
          session_id: created.session_id,
          title: created.title,
          type: created.type,
          state_summary: '',
          turn_count: 0,
          updated_at: new Date().toISOString(),
        }]);
        setInternalActiveId(created.session_id);
      } catch (e) {
        // Suppress aborted-on-switch errors (same pattern as the
        // transcript-load effect — ERR_CANCELED is benign).
        const code = (e as { code?: string })?.code;
        if (code === 'ERR_CANCELED') return;
        if (alive) toast.error(extractErr(e, '会话列表加载失败'));
      }
    })();
    return () => {
      alive = false;
      controller.abort();
    };
  }, [externalMode, interviewId, sessionType]);

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
  }, [externalMode, interviewId, sessionType, creating, sessions.length]);

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
      setSessions((s) => {
        const next = s.filter((x) => x.session_id !== id);
        if (internalActiveId === id) setInternalActiveId(next[0]?.session_id ?? null);
        return next;
      });
      setPendingDelete(null);
    } catch (e) { toast.error(extractErr(e, '删除会话失败')); }
    finally { setDeletingChat(false); }
  }, [pendingDelete, internalActiveId, onSessionDeleted]);

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
  }, [renaming]);

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
