/**
 * /general-chat — standalone "ChatGPT-style" page detached from the
 * review workflow.
 *
 * Layout mirrors ReviewPage: a left sidebar listing this user's general
 * chat sessions, and the right pane reuses ``ChatPanel`` to drive the
 * actual messaging. Each session in the left list owns its own
 * conversation dropdown via ChatPanel's internals — so this page only
 * needs to manage session-level CRUD (create / rename / delete) plus
 * "which session is selected".
 *
 * Why a dedicated page (instead of a session_type='general' inside the
 * review page): general chat doesn't anchor to an interview record, so
 * the review page's interview-record sidebar was an awkward host. Users
 * also want to leave general chat open while the review page deals
 * with uploads + analysis, which means it deserves its own URL the
 * browser back/forward stack can navigate.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { Plus, Pencil, X as XIcon, MessageSquare, Sparkles } from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import { ChatPanel } from '@/pages/review/ChatPanel';
import type { ChatSessionListItem } from '@/types/api';

export function GeneralChatPage() {
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  // Inline rename inside the sidebar — same pattern as review page.
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  const refresh = useCallback(async (preserveActive = true) => {
    setLoading(true);
    try {
      const rows = await listChatSessions({ session_type: 'general' });
      setSessions(rows);
      if (rows.length === 0) {
        setActiveId(null);
      } else if (!preserveActive || !rows.some((r) => r.session_id === activeId)) {
        setActiveId(rows[0].session_id);
      }
    } catch (e) {
      toast.error(extractErr(e, '对话列表加载失败'));
    } finally {
      setLoading(false);
    }
    // activeId is read inside the closure but we don't want refresh to
    // re-create on every active change (would refetch unnecessarily).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { void refresh(false); }, [refresh]);

  // Focus the inline rename input when entering rename mode.
  useEffect(() => {
    if (!renaming) return;
    requestAnimationFrame(() => {
      const el = renameInputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [renaming]);

  const onNew = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const created = await createChatSession({
        session_type: 'general',
        title: `通用对话 ${sessions.length + 1}`,
      });
      // Optimistic prepend — the new session is the most recent so it
      // belongs at the top.
      setSessions((s) => [
        {
          session_id: created.session_id,
          title: created.title,
          session_type: created.session_type,
          state_summary: '',
          turn_count: 0,
          updated_at: new Date().toISOString(),
        },
        ...s,
      ]);
      setActiveId(created.session_id);
    } catch (e) {
      toast.error(extractErr(e, '创建对话失败'));
    } finally {
      setCreating(false);
    }
  };

  // Pending delete confirmation. Replaces the off-brand native
  // ``window.confirm`` (Chrome titles it "Code" because it's not a
  // PWA dialog — looks like a Chrome extension popup). Same
  // ConfirmDialog used by Library, MemoryTab, and ChatPanel — keeps
  // the visual language consistent across delete affordances.
  const [pendingDelete, setPendingDelete] = useState<{ id: string; title: string } | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);

  const onDelete = useCallback((id: string) => {
    const s = sessions.find((x) => x.session_id === id);
    setPendingDelete({ id, title: s?.title ?? '该会话' });
  }, [sessions]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete) return;
    const id = pendingDelete.id;
    setDeletingChat(true);
    try {
      await deleteChatSession(id);
      // Clean up the per-session localStorage drafts/mode so we
      // don't leak keys (same cleanup ChatPanel does on its own
      // delete path).
      try { localStorage.removeItem(`chat-draft:${id}`); } catch { /* ignore */ }
      try { localStorage.removeItem(`chat-mode:${id}`); } catch { /* ignore */ }
      setSessions((s) => {
        const next = s.filter((x) => x.session_id !== id);
        if (activeId === id) setActiveId(next[0]?.session_id ?? null);
        return next;
      });
      setPendingDelete(null);
    } catch (e) {
      toast.error(extractErr(e, '删除对话失败'));
    } finally {
      setDeletingChat(false);
    }
  }, [pendingDelete, activeId]);

  const commitRename = useCallback(async () => {
    if (!renaming) return;
    const title = renaming.title.trim();
    if (!title) { setRenaming(null); return; }
    try {
      await renameChatSession(renaming.id, title);
      setSessions((s) =>
        s.map((x) => x.session_id === renaming.id ? { ...x, title } : x),
      );
    } catch (e) {
      toast.error(extractErr(e, '重命名失败'));
    } finally {
      setRenaming(null);
    }
  }, [renaming]);

  const activeSession = sessions.find((s) => s.session_id === activeId);

  return (
    <div className="flex h-full bg-cream-50">
      {/* Left sidebar: session list */}
      <aside className="w-[280px] shrink-0 bg-white border-r border-stone-200 flex flex-col">
        <div className="h-14 px-4 flex items-center justify-between border-b border-stone-100">
          <div className="text-sm font-semibold text-stone-800">通用对话</div>
          <button
            onClick={onNew}
            disabled={creating}
            title="新建一段对话"
            className="inline-flex items-center gap-1 px-2.5 h-8 rounded-lg border border-dashed border-stone-300 text-stone-600 hover:bg-stone-50 hover:border-primary-300 hover:text-primary-700 text-xs disabled:opacity-50"
          >
            <Plus size={13} />
            <span>新建</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loading ? (
            <div className="p-6 flex items-center justify-center text-stone-400">
              <Spinner size={16} />
            </div>
          ) : sessions.length === 0 ? (
            <div className="p-6 text-center text-stone-400 text-sm">
              <MessageSquare size={20} className="mx-auto mb-2 text-stone-300" />
              <div>还没有对话</div>
              <div className="text-[11px] mt-1">点上方「新建」开始</div>
            </div>
          ) : (
            sessions.map((s) => {
              const act = s.session_id === activeId;
              const editing = renaming?.id === s.session_id;
              return (
                <div
                  key={s.session_id}
                  className={[
                    'group relative px-3 py-2.5 mb-1 rounded-lg cursor-pointer transition-colors',
                    act ? 'bg-primary-50' : 'hover:bg-stone-50',
                  ].join(' ')}
                  onClick={() => !editing && setActiveId(s.session_id)}
                >
                  {editing ? (
                    <input
                      ref={renameInputRef}
                      value={renaming!.title}
                      onChange={(e) => setRenaming({ id: s.session_id, title: e.target.value })}
                      onBlur={() => { void commitRename(); }}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        e.stopPropagation();
                        if (e.key === 'Enter') { e.preventDefault(); void commitRename(); }
                        else if (e.key === 'Escape') { e.preventDefault(); setRenaming(null); }
                      }}
                      placeholder="按 Enter 保存，Esc 取消"
                      className="w-full text-sm px-2 py-1 border border-primary-300 rounded outline-none focus:ring-2 focus:ring-primary-200"
                    />
                  ) : (
                    <>
                      <div className={[
                        'text-sm truncate pr-12',
                        act ? 'text-primary-700 font-semibold' : 'text-stone-700',
                      ].join(' ')}>
                        {s.title}
                      </div>
                      {s.turn_count > 0 && (
                        <div className="text-[11px] text-stone-400 mt-0.5">
                          {s.turn_count} 轮 · {new Date(s.updated_at).toLocaleString('zh-CN', {
                            month: '2-digit', day: '2-digit',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </div>
                      )}
                      <div className="absolute right-2 top-2 flex items-center gap-1 opacity-0 group-hover:opacity-100">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setRenaming({ id: s.session_id, title: s.title });
                          }}
                          title="重命名"
                          className="w-6 h-6 rounded text-stone-400 hover:text-stone-700 hover:bg-stone-100 flex items-center justify-center"
                        >
                          <Pencil size={12} />
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); void onDelete(s.session_id); }}
                          title="删除"
                          className="w-6 h-6 rounded text-stone-400 hover:text-danger-500 hover:bg-danger-50 flex items-center justify-center"
                        >
                          <XIcon size={12} />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* Right pane: reuse ChatPanel for the active session. ``width``
          is wide-open because there's no resizer on this page — keep
          it simple, the side nav already takes its share. */}
      {activeId ? (
        <div className="flex-1 min-w-0 flex">
          <ChatPanel
            sessionId={activeId}
            sessionTitle={activeSession?.title ?? '通用对话'}
            flexible
          />
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-stone-400">
          <div className="text-center">
            <div className="w-14 h-14 mx-auto rounded-2xl bg-white border border-stone-200 flex items-center justify-center mb-3">
              <Sparkles size={22} className="text-primary-500" />
            </div>
            <div className="text-base text-stone-600 font-medium mb-1">点左侧「新建」开始</div>
            <div className="text-xs leading-relaxed max-w-xs">
              通用对话不绑定具体面试，适合写代码、刷算法、查概念这类自由聊天。
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!pendingDelete}
        danger
        title="删除对话"
        description={
          pendingDelete
            ? `确定删除「${pendingDelete.title}」？该对话下的所有消息将被永久删除，不可恢复。`
            : ''
        }
        confirmText="删除"
        loading={deletingChat}
        onConfirm={() => { void confirmDelete(); }}
        onCancel={() => { if (!deletingChat) setPendingDelete(null); }}
      />
    </div>
  );
}
