/**
 * /general-chat — the Career Agent control plane, detached from the
 * review workflow while sharing the conversation kernel.
 *
 * Layout mirrors ReviewPage: a left sidebar listing this user's general
 * chat sessions, and the right pane reuses ``ChatPanel`` to drive the
 * actual messaging. Each session in the left list owns its own
 * conversation dropdown via ChatPanel's internals — so this page only
 * needs to manage session-level CRUD (create / rename / delete) plus
 * "which session is selected".
 *
 * Why a dedicated page (instead of a type='general' inside the
 * review page): general chat doesn't anchor to an interview record, so
 * the review page's interview-record sidebar was an awkward host. Users
 * also want to leave general chat open while the review page deals
 * with uploads + analysis, which means it deserves its own URL the
 * browser back/forward stack can navigate.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, X as XIcon, MessageSquare } from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  getChatSessionDeletionImpact,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import type { ProductObjectReference, ConversationDeletionImpact } from '@/types/api';
import { useToastOnError } from '@/hooks/useToastOnError';
import { ChatPanel } from '@/pages/review/chat/ChatPanel';
import { CopilotStatusSummary } from './CopilotStatusSummary';
import { clearPersistedSessionState } from '@/pages/review/chat/usePersistedSessionState';
import type { ChatSessionListItem } from '@/types/api';
import { collaborationStarters, readStarter } from '@/lib/collaborationStarters';
import {
  clearCopilotObjectHandoff,
  productObjectReferenceLabel,
  readCopilotObjectHandoff,
} from '@/lib/copilotObjectReference';

// Same key family as ChatPanel's internal (debrief) session list — one
// cache namespace for every chat-session list in the app.
const SESSIONS_KEY = ['chat', 'sessions', { type: 'general' }] as const;

interface Props {
  embedded?: boolean;
  objectReference?: ProductObjectReference | null;
  onObjectReferenceConsumed?: () => void;
}

export function GeneralChatPage({ embedded = false, objectReference = null, onObjectReferenceConsumed }: Props = {}) {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [embeddedSessionId, setEmbeddedSessionId] = useState<string | null>(null);
  const activeId = embedded ? embeddedSessionId : searchParams.get('session');
  const starterId = embedded ? null : readStarter(searchParams.get('start'));
  const starter = starterId ? collaborationStarters[starterId] : null;
  const setActiveId = (id: string) => embedded ? setEmbeddedSessionId(id) : setSearchParams((previous) => {
    const next = new URLSearchParams(previous);
    next.set('session', id);
    next.delete('start');
    return next;
  });
  const [creating, setCreating] = useState(false);
  const creationRequest = useRef<{ intent: string; id: string } | null>(null);
  const creationInFlight = useRef(false);
  // Inline rename inside the sidebar — same pattern as review page.
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const productObjectReference = useMemo(
    () => embedded ? objectReference : readCopilotObjectHandoff(searchParams),
    [embedded, objectReference, searchParams],
  );
  const clearProductObjectReference = useCallback(() => {
    if (embedded) onObjectReferenceConsumed?.();
    else setSearchParams(clearCopilotObjectHandoff(searchParams), { replace: true });
  }, [embedded, onObjectReferenceConsumed, searchParams, setSearchParams]);

  const { data: sessions = [], isPending: loading, error, refetch } = useQuery({
    queryKey: SESSIONS_KEY,
    queryFn: ({ signal }) => listChatSessions({ type: 'general' }, { signal }),
  });
  useToastOnError(error, '对话列表加载失败');

  /** Mutate the cached list in place (create / rename / delete below). */
  const setSessions = useCallback(
    (updater: (cur: ChatSessionListItem[]) => ChatSessionListItem[]) => {
      // Cancel any in-flight background refetch first — otherwise its
      // (pre-mutation) response could land after this write and undo it.
      void queryClient.cancelQueries({ queryKey: SESSIONS_KEY });
      queryClient.setQueryData<ChatSessionListItem[]>(
        SESSIONS_KEY,
        (cur) => updater(cur ?? []),
      );
    },
    [queryClient],
  );

  const selectedId = starter ? null : activeId ?? sessions[0]?.session_id ?? null;

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
    if (creationInFlight.current) return;
    creationInFlight.current = true;
    setCreating(true);
    const intent = starterId ?? 'general';
    if (creationRequest.current?.intent !== intent) creationRequest.current = { intent, id: crypto.randomUUID() };
    try {
      const created = await createChatSession({
        client_request_id: creationRequest.current.id,
        type: 'general',
        title: starter?.title ?? `求职任务 ${sessions.length + 1}`,
      });
      // Optimistic prepend — the new session is the most recent so it
      // belongs at the top.
      setSessions((s) => [
        {
          session_id: created.session_id,
          title: created.title,
          type: created.type,
          state_summary: '',
          mode: 'agent',
          execution_mode: created.execution_mode,
          execution_mode_version: created.execution_mode_version,
          turn_count: 0,
          updated_at: new Date().toISOString(),
        },
        ...s.filter((row) => row.session_id !== created.session_id),
      ]);
      if (starter) {
        // Use the same per-session draft owner as the composer. A starter is
        // editable user input and must never become an automatic model call.
        try { localStorage.setItem(`chat-draft:${created.session_id}`, starter.draft); }
        catch { toast.info('浏览器未能保存起步草稿，请在对话中描述你的目标'); }
      }
      setActiveId(created.session_id);
      creationRequest.current = null;
      void queryClient.invalidateQueries({ queryKey: ['workspace'] });
    } catch (e) {
      toast.error(extractErr(e, '创建对话失败'));
    } finally {
      creationInFlight.current = false;
      setCreating(false);
    }
  };

  // Pending delete confirmation. Replaces the off-brand native
  // ``window.confirm`` (Chrome titles it "Code" because it's not a
  // PWA dialog — looks like a Chrome extension popup). Same
  // ConfirmDialog used by Library and ChatPanel — keeps
  // the visual language consistent across delete affordances.
  const [pendingDelete, setPendingDelete] = useState<{
    id: string;
    title: string;
    impact: ConversationDeletionImpact | null;
    error: string | null;
  } | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);

  const onDelete = useCallback((id: string) => {
    const s = sessions.find((x) => x.session_id === id);
    const title = s?.title ?? '该会话';
    setPendingDelete({ id, title, impact: null, error: null });
    void getChatSessionDeletionImpact(id).then(
      (impact) => setPendingDelete((current) => (
        current?.id === id ? { ...current, impact, error: null } : current
      )),
      (error) => setPendingDelete((current) => (
        current?.id === id
          ? { ...current, error: extractErr(error, '删除影响暂时无法读取') }
          : current
      )),
    );
  }, [sessions]);

  const confirmDelete = useCallback(async () => {
    if (!pendingDelete?.impact) return;
    const id = pendingDelete.id;
    setDeletingChat(true);
    try {
      await deleteChatSession(id, pendingDelete.impact);
      // Clean up the per-session localStorage drafts/mode so we don't
      // leak keys (same helper ChatPanel uses on its own delete path).
      clearPersistedSessionState(id);
      // Selection fallback is handled by the keep-selection-valid effect
      // above once the cached list no longer contains the active id.
      setSessions((s) => s.filter((x) => x.session_id !== id));
      setPendingDelete(null);
    } catch (e) {
      toast.error(extractErr(e, '删除对话失败'));
    } finally {
      setDeletingChat(false);
    }
  }, [pendingDelete, setSessions]);

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
  }, [renaming, setSessions]);

  const activeSession = sessions.find((s) => s.session_id === selectedId);

  return (
    <div className={embedded ? "copilot-page copilot-embedded" : "copilot-page"}>
      {/* Left sidebar: session list */}
      <aside className="copilot-session-list">
        <div className="h-14 px-4 flex items-center justify-between border-b border-stone-100">
          <div className="text-sm font-semibold text-stone-800">求职 Copilot</div>
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
        <CopilotStatusSummary />
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
              const act = s.session_id === selectedId;
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
      {error ? <div className="copilot-welcome" role="alert"><div><h2>暂时无法读取协作记录</h2><p>这不代表记录已丢失。恢复连接后可以继续原来的任务。</p><button className="today-primary-link" onClick={() => { void refetch(); }}>重新加载</button></div></div> : loading ? <div className="copilot-welcome" role="status">正在读取协作记录…</div> : selectedId ? (
        <div className="flex-1 min-w-0 flex">
          <ChatPanel
            sessionId={selectedId}
            sessionTitle={activeSession?.title ?? '求职 Copilot'}
            fixedMode="AGENT"
            flexible
            productObjectReferences={productObjectReference ? [productObjectReference] : []}
            onRemoveProductObjectReference={clearProductObjectReference}
            onProductObjectReferencesConsumed={clearProductObjectReference}
          />
        </div>
      ) : (
        <div className="copilot-welcome">
          <div>
            <span className="today-dateline">与你一起推进求职</span>
            <h2>{starter?.title ?? '今天，想先完成什么？'}</h2>
            <p>{starter?.detail ?? '描述一个具体目标，例如修改简历或准备面试。你可以随时补充资料，协作记录会保存在左侧。'}</p>
            {starter && <p>接下来会为你准备一份可编辑的起步消息。确认后发送，再一起补充需要的信息。</p>}
            <button className="today-primary-link" disabled={creating} onClick={onNew}>{creating ? '正在创建…' : starter ? '开始这项准备' : '开始新对话'}</button>
            {productObjectReference && (
              <div className="mt-3 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-xs text-primary-700">
                已选择：{productObjectReferenceLabel(productObjectReference)}。新建对话后会作为本轮显式输入。
              </div>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!pendingDelete}
        danger
        title="删除对话"
        description={
          pendingDelete
            ? pendingDelete.error
              ?? (pendingDelete.impact
                ? `确定删除「${pendingDelete.title}」？\n\n${pendingDelete.impact.disclosures.join('\n')}`
                : '正在读取待发送输入、附件、消息与外部调用影响……')
            : ''
        }
        confirmText="删除"
        loading={deletingChat}
        confirmDisabled={!pendingDelete?.impact || !!pendingDelete?.error}
        onConfirm={() => { void confirmDelete(); }}
        onCancel={() => { if (!deletingChat) setPendingDelete(null); }}
      />
    </div>
  );
}
