/**
 * ChatPanel — the right-pane chat UI.
 *
 * Two scope shapes:
 *
 *  1. **Review (debrief) mode** — caller passes ``interviewId``. The panel
 *     fetches its own session list (``session_type='debrief', interview_id``)
 *     and renders a dropdown for new / rename / delete + active-session
 *     selection. Auto-selects the most recent session; auto-creates
 *     "会话 1" the first time the user opens a record with no sessions.
 *
 *  2. **External mode** — caller passes ``sessionId`` directly (used by
 *     ``GeneralChatPage`` where the left sidebar already owns the session
 *     list). The dropdown / CRUD UI is hidden; ChatPanel just renders
 *     the chat for whatever sessionId was handed in.
 *
 * The transport is SSE (``streamChatSSE``). Mock-style WebSocket has been
 * removed — see ``app/api/chat/streaming.py`` for the rationale (GPT /
 * Claude / Gemini all use SSE for one-way text).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Send, Paperclip, Bot, MessageSquare, Sparkles, ChevronDown,
  Plus, Pencil, X as XIcon, Check, Brain,
} from 'lucide-react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Spinner } from '@/components/ui/Spinner';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  getChatHistory,
  getSessionMemoryRecall,
  listChatSessions,
  renameChatSession,
  setSessionMemoryRecall,
  streamChatSSE,
} from '@/api/chat';
import { uploadKnowledgeFile } from '@/api/knowledge';
import { getModelsRuntime, updateModelsRuntime, getModelsCatalog } from '@/api/models';
import type { ChatMessageItem, ChatSessionListItem, ModelProfile, ModelRole } from '@/types/api';

interface Props {
  /** Review/debrief mode: bind to this interview record. ChatPanel will
   *  maintain its own session list filtered by (session_type=debrief,
   *  interview_id=interviewId). Mutually exclusive with ``sessionId``. */
  interviewId?: string | null;
  /** External mode: caller manages the session list and tells ChatPanel
   *  exactly which session to drive. Mutually exclusive with ``interviewId``. */
  sessionId?: string | null;
  /** Header subtitle — usually the interview record's title (review page)
   *  or the user-picked session title (general-chat page). */
  sessionTitle?: string | null;
  /** Filter type for internal session list. Only consulted when
   *  ``interviewId`` is given — defaults to ``"debrief"``. */
  sessionType?: 'debrief' | 'general';
  /** Fixed-width mode (default for review page with a resizer); set
   *  ``flexible`` to stretch into the parent's remaining space. */
  width?: number;
  flexible?: boolean;
}

interface UIMessage { role: 'user' | 'assistant' | 'system'; content: string; }
interface Attachment { doc_id: string; filename: string; }

type Mode = 'CHAT' | 'AGENT';

interface SessionRuntime {
  abort: AbortController | null;  // in-flight SSE aborter (null between turns)
  messages: UIMessage[];
  partial: string;
  status: string;
  streaming: boolean;
  hidePartialBar: boolean;
  loadedHistory: boolean;
}

function toUI(m: ChatMessageItem): UIMessage {
  const r = (m.role ?? '').toLowerCase();
  if (r === 'user') return { role: 'user', content: m.content };
  if (r === 'assistant' || r === 'agent' || r === 'ai' || r === 'bot') {
    return { role: 'assistant', content: m.content };
  }
  return { role: 'system', content: m.content };
}

export function ChatPanel({
  interviewId,
  sessionId: externalSessionId,
  sessionTitle,
  sessionType = 'debrief',
  width = 400,
  flexible = false,
}: Props) {
  // External-mode (caller-controlled): ChatPanel becomes a thin shell;
  // session list state stays empty.
  const externalMode = externalSessionId !== undefined && externalSessionId !== null;

  // ── Session list state (debrief/internal mode) ───────────────────────
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [internalActiveId, setInternalActiveId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);

  // The active session id either comes straight from the prop (external)
  // or from our internal list state.
  const activeSessionId = externalMode ? externalSessionId : internalActiveId;

  // ── Chat input / mode / attachments ──────────────────────────────────
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<Mode>('CHAT');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);

  // ── Memory recall toggle (per-session resolved value) ────────────────
  const [recallEnabled, setRecallEnabled] = useState(false);
  const [togglingRecall, setTogglingRecall] = useState(false);

  // ── Model picker ─────────────────────────────────────────────────────
  const [modelOpen, setModelOpen] = useState(false);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [selection, setSelection] = useState<{ primary: string; agent: string }>({ primary: '', agent: '' });

  // ── Refs ─────────────────────────────────────────────────────────────
  const listRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<HTMLDivElement | null>(null);
  const sessionDropdownRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  // ── Per-session SSE runtime cache ────────────────────────────────────
  const runtimes = useRef<Map<string, SessionRuntime>>(new Map());
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((n) => n + 1), []);
  const getRuntime = useCallback((id: string): SessionRuntime => {
    let r = runtimes.current.get(id);
    if (!r) {
      r = {
        abort: null, messages: [], partial: '', status: '',
        streaming: false, hidePartialBar: false, loadedHistory: false,
      };
      runtimes.current.set(id, r);
    }
    return r;
  }, []);

  // ── Focus the rename input whenever a rename starts ──────────────────
  useEffect(() => {
    if (!renaming) return;
    requestAnimationFrame(() => {
      const el = renameInputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [renaming]);

  // ── Internal mode: load + auto-pick + auto-create session list ───────
  // (One round-trip per interviewId change; the auto-create branch only
  // fires when the result list is empty.)
  useEffect(() => {
    if (externalMode) return;
    if (!interviewId) {
      setSessions([]);
      setInternalActiveId(null);
      return;
    }
    let alive = true;
    (async () => {
      try {
        const rows = await listChatSessions({
          session_type: sessionType,
          interview_id: interviewId,
        });
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
        const created = await createChatSession({
          session_type: sessionType,
          interview_id: interviewId,
          title: '会话 1',
        });
        if (!alive) return;
        setSessions([{
          session_id: created.session_id,
          title: created.title,
          session_type: created.session_type,
          state_summary: '',
          turn_count: 0,
          updated_at: new Date().toISOString(),
        }]);
        setInternalActiveId(created.session_id);
      } catch (e) {
        if (alive) toast.error(extractErr(e, '会话列表加载失败'));
      }
    })();
    return () => { alive = false; };
  }, [externalMode, interviewId, sessionType]);

  // ── Lazy-load history for the active session ─────────────────────────
  useEffect(() => {
    if (!activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.loadedHistory) return;
    let alive = true;
    getChatHistory(activeSessionId, 0, 100)
      .then((rows) => {
        if (!alive) return;
        const rt = getRuntime(activeSessionId);
        if (rt.messages.length === 0) rt.messages = rows.map(toUI);
        rt.loadedHistory = true;
        bump();
      })
      .catch(() => { /* empty history is fine */ });
    return () => { alive = false; };
  }, [activeSessionId, getRuntime, bump]);

  // ── Abort all in-flight SSE on unmount ──────────────────────────────
  useEffect(() => {
    const map = runtimes.current;
    return () => { map.forEach((r) => r.abort?.abort()); };
  }, []);

  // ── Memory recall: fetch resolved value on session change ────────────
  useEffect(() => {
    if (!activeSessionId) { setRecallEnabled(false); return; }
    let alive = true;
    getSessionMemoryRecall(activeSessionId)
      .then((v) => { if (alive) setRecallEnabled(v); })
      .catch(() => { /* leave at false */ });
    return () => { alive = false; };
  }, [activeSessionId]);

  const toggleRecall = useCallback(async () => {
    if (!activeSessionId || togglingRecall) return;
    const next = !recallEnabled;
    setRecallEnabled(next);
    setTogglingRecall(true);
    try { await setSessionMemoryRecall(activeSessionId, next); }
    catch (e) {
      setRecallEnabled(!next);
      toast.error(extractErr(e, '切换记忆召回失败'));
    } finally { setTogglingRecall(false); }
  }, [activeSessionId, recallEnabled, togglingRecall]);

  // ── Models: load + refresh on focus + close on outside click ─────────
  const refreshModels = useCallback(() => {
    getModelsRuntime()
      .then((rt) => setSelection({
        primary: rt.resolved?.primary?.profile_id ?? '',
        agent: rt.resolved?.agent?.profile_id ?? '',
      }))
      .catch(() => {});
    getModelsCatalog()
      .then((c) => setProfiles(c.profiles))
      .catch(() => {});
  }, []);
  useEffect(() => { refreshModels(); }, [refreshModels]);
  useEffect(() => {
    const onFocus = () => refreshModels();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refreshModels]);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!modelRef.current?.contains(e.target as Node)) setModelOpen(false);
      if (!sessionDropdownRef.current?.contains(e.target as Node)) setSessionDropdownOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [tick, activeSessionId]);

  // ── Session CRUD (internal mode) ─────────────────────────────────────
  const newChat = useCallback(async () => {
    if (externalMode || !interviewId || creating) return;
    setCreating(true);
    try {
      const created = await createChatSession({
        session_type: sessionType,
        interview_id: interviewId,
        title: `会话 ${sessions.length + 1}`,
      });
      setSessions((s) => [{
        session_id: created.session_id,
        title: created.title,
        session_type: created.session_type,
        state_summary: '',
        turn_count: 0,
        updated_at: new Date().toISOString(),
      }, ...s]);
      setInternalActiveId(created.session_id);
      setSessionDropdownOpen(false);
    } catch (e) {
      toast.error(extractErr(e, '创建会话失败'));
    } finally { setCreating(false); }
  }, [externalMode, interviewId, sessionType, creating, sessions.length]);

  const removeChat = useCallback(async (id: string) => {
    if (externalMode) return;
    if (!window.confirm('确定删除这段会话？所有消息会被永久删除。')) return;
    try {
      await deleteChatSession(id);
      const r = runtimes.current.get(id);
      r?.abort?.abort();
      runtimes.current.delete(id);
      setSessions((s) => {
        const next = s.filter((x) => x.session_id !== id);
        if (internalActiveId === id) setInternalActiveId(next[0]?.session_id ?? null);
        return next;
      });
    } catch (e) { toast.error(extractErr(e, '删除会话失败')); }
  }, [externalMode, internalActiveId]);

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

  // ── Attachments ──────────────────────────────────────────────────────
  const onAttachFiles = async (files: FileList) => {
    setUploading(true);
    const added: Attachment[] = [];
    for (const f of Array.from(files)) {
      try {
        const doc = await uploadKnowledgeFile(f, { category: 'chat_attachment', source_type: 'official_docs' });
        added.push({ doc_id: doc.id, filename: f.name });
      } catch { toast.error(`附件上传失败：${f.name}`); }
    }
    if (added.length > 0) {
      setAttachments((arr) => [...arr, ...added]);
      toast.success(`已附加 ${added.length} 个文件`);
    }
    setUploading(false);
  };

  // ── Send via SSE ─────────────────────────────────────────────────────
  const send = () => {
    const text = input.trim();
    if (!text || !activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.streaming) return;
    let payload = text;
    if (attachments.length > 0) {
      const tail = attachments.map((a) => `[附件: ${a.filename} (doc=${a.doc_id})]`).join('\n');
      payload = `${tail}\n\n${text}`;
    }
    r.messages.push({ role: 'user', content: payload });
    r.partial = '';
    r.status = '';
    r.hidePartialBar = false;
    r.streaming = true;
    setInput('');
    setAttachments([]);
    bump();

    const ac = new AbortController();
    r.abort = ac;
    const sid = activeSessionId;
    const finalize = (errMsg?: string) => {
      const rt = getRuntime(sid);
      if (rt.partial.trim()) {
        rt.messages.push({ role: 'assistant', content: rt.partial });
      } else if (errMsg) {
        rt.messages.push({ role: 'system', content: `（连接中断：${errMsg}）` });
      }
      rt.partial = '';
      rt.status = '';
      rt.streaming = false;
      rt.hidePartialBar = false;
      rt.abort = null;
      bump();
    };
    streamChatSSE(sid, payload, {
      onChunk: (delta) => {
        const rt = getRuntime(sid);
        rt.partial += delta;
        rt.streaming = true;
        bump();
      },
      onStatus: (status) => {
        const rt = getRuntime(sid);
        rt.status = status;
        rt.streaming = true;
        bump();
      },
    }, { signal: ac.signal })
      .then(() => finalize())
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') { finalize(); return; }
        finalize(extractErr(err, '连接失败'));
        toast.error(extractErr(err, '发送失败'));
      });
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  // ── Model picker ────────────────────────────────────────────────────
  const activeRole: ModelRole = mode === 'AGENT' ? 'agent' : 'primary';
  const activeProfileId = selection[activeRole];
  const activeProfile = profiles.find((p) => p.id === activeProfileId);
  const activeModelName = activeProfile?.display_name ?? '未配置';
  const onPickModel = async (p: ModelProfile) => {
    if (!p.ready) { toast.warn(`需先配置 ${p.api_key_env}`); return; }
    if (activeRole === 'agent' && !p.supports_function_calling) {
      toast.warn('AGENT 角色需要支持函数调用的模型');
      return;
    }
    setModelOpen(false);
    const prev = selection[activeRole];
    setSelection((s) => ({ ...s, [activeRole]: p.id }));
    try {
      await updateModelsRuntime({ [activeRole]: p.id } as Partial<Record<ModelRole, string>>);
      toast.success(`已切换 ${activeRole === 'agent' ? 'Agent' : '主对话'}：${p.display_name}`);
    } catch {
      setSelection((s) => ({ ...s, [activeRole]: prev }));
      toast.error('切换模型失败');
    }
  };

  // ── Derived render state ────────────────────────────────────────────
  const subtitle = sessionTitle ?? '复盘对话';
  const activeRuntime = activeSessionId ? getRuntime(activeSessionId) : null;
  const messages = activeRuntime?.messages ?? [];
  const partial = activeRuntime?.partial ?? '';
  const statusHint = activeRuntime?.status ?? '';
  const streaming = !!activeRuntime?.streaming;
  const hidePartialBar = !!activeRuntime?.hidePartialBar;
  const activeSession = sessions.find((s) => s.session_id === activeSessionId);
  const activeSessionTitle = activeSession?.title ?? '选择会话';

  // ── Streaming-status set for the dropdown's per-row dot ─────────────
  const streamingSet = useMemo(() => {
    const set = new Set<string>();
    runtimes.current.forEach((r, id) => { if (r.streaming) set.add(id); });
    return set;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  // ── Virtualizer ─────────────────────────────────────────────────────
  const messageVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => 96,
    overscan: 6,
    getItemKey: (index) => `${activeSessionId ?? 'none'}:${index}`,
  });

  // ────────────────────────────────────────────────────────────────────
  return (
    <aside
      style={flexible ? undefined : { width }}
      className={[
        'bg-white border-l border-stone-200 flex flex-col',
        flexible ? 'flex-1 min-w-0' : 'shrink-0',
      ].join(' ')}
    >
      {/* Row 1: subtitle + model picker */}
      <div className="px-4 pt-4 pb-2.5 flex items-center justify-between gap-2 border-b border-stone-100">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-stone-800 truncate">{subtitle}</div>
          <div className="text-[11px] text-stone-400 mt-0.5 truncate font-mono">{activeModelName}</div>
        </div>
        <div ref={modelRef} className="relative shrink-0">
          <button
            onClick={() => setModelOpen((v) => !v)}
            title={`${activeRole === 'agent' ? 'Agent' : '主对话'} 当前模型`}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-stone-200 bg-stone-50 text-stone-700 text-xs hover:bg-stone-100 font-mono"
          >
            <Sparkles size={12} className={activeRole === 'agent' ? 'text-primary-500' : 'text-accent-700'} />
            <span className="text-[10px] text-stone-400">{activeRole === 'agent' ? 'A:' : ''}</span>
            <span className="truncate max-w-[100px]">{activeModelName}</span>
            <ChevronDown size={12} className="text-stone-400" />
          </button>
          {modelOpen && (
            <div className="absolute top-full right-0 mt-1 w-[260px] max-h-[340px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
              <div className="px-2.5 py-1.5 text-[11px] text-stone-500 border-b border-stone-100 mb-1">
                选择「{activeRole === 'agent' ? 'Agent · 工具调用' : '主对话'}」的模型
              </div>
              {profiles.length === 0 && <div className="px-2.5 py-2 text-xs text-stone-400">载入中…</div>}
              {profiles
                .filter((p) => activeRole !== 'agent' || p.supports_function_calling)
                .map((p) => {
                  const sel = p.id === activeProfileId;
                  return (
                    <div
                      key={p.id}
                      onClick={() => onPickModel(p)}
                      className={[
                        'px-2.5 py-1.5 rounded-md cursor-pointer leading-tight',
                        sel ? 'bg-primary-50 text-primary-700' : 'text-stone-700 hover:bg-stone-50',
                        !p.ready ? 'opacity-60' : '',
                      ].join(' ')}
                    >
                      <div className="font-sans font-medium text-[13px]">{p.display_name}</div>
                      <div className="text-[11px] text-stone-400 truncate font-mono">{p.model}</div>
                      {!p.ready && <div className="text-[11px] text-warning-700">未配置 {p.api_key_env}</div>}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      </div>

      {/* Row 2: session dropdown + new/rename — only in internal mode */}
      {!externalMode && interviewId && (
        <div className="px-3 py-2 border-b border-stone-200 flex items-center gap-1.5">
          <div ref={sessionDropdownRef} className="relative flex-1 min-w-0">
            {renaming && renaming.id === activeSessionId ? (
              <input
                ref={renameInputRef}
                value={renaming.title}
                onChange={(e) => setRenaming({ id: renaming.id, title: e.target.value })}
                onBlur={() => { void commitRename(); }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); void commitRename(); }
                  else if (e.key === 'Escape') { e.preventDefault(); setRenaming(null); }
                }}
                placeholder="按 Enter 保存，Esc 取消"
                className="w-full px-3 py-2 text-sm border border-primary-300 rounded-lg outline-none focus:ring-2 focus:ring-primary-200"
              />
            ) : (
              <button
                onClick={() => setSessionDropdownOpen((v) => !v)}
                disabled={sessions.length === 0}
                className="w-full inline-flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-700 text-sm disabled:opacity-60"
              >
                <span className="flex items-center gap-2 min-w-0">
                  <MessageSquare size={13} className="text-stone-500 shrink-0" />
                  <span className="truncate">{activeSessionId ? activeSessionTitle : '尚无会话'}</span>
                  {streaming && (
                    <span className="shrink-0 inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
                  )}
                </span>
                <ChevronDown size={14} className={[
                  'text-stone-400 transition-transform',
                  sessionDropdownOpen ? 'rotate-180' : '',
                ].join(' ')} />
              </button>
            )}
            {sessionDropdownOpen && (
              <div className="absolute left-0 right-0 top-full mt-1 max-h-[320px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
                {sessions.length === 0 && (
                  <div className="px-3 py-3 text-sm text-stone-400 text-center">点右侧 + 新建一段会话</div>
                )}
                {sessions.map((s) => {
                  const act = s.session_id === activeSessionId;
                  const isStreaming = streamingSet.has(s.session_id);
                  return (
                    <div
                      key={s.session_id}
                      className={[
                        'group flex items-center gap-2 px-2.5 py-1.5 rounded-md cursor-pointer',
                        act ? 'bg-primary-50' : 'hover:bg-stone-50',
                      ].join(' ')}
                    >
                      <span
                        onClick={() => { setInternalActiveId(s.session_id); setSessionDropdownOpen(false); }}
                        onDoubleClick={(e) => { e.stopPropagation(); setRenaming({ id: s.session_id, title: s.title }); }}
                        className={[
                          'flex-1 min-w-0 truncate text-sm',
                          act ? 'text-primary-700 font-semibold' : 'text-stone-700',
                        ].join(' ')}
                        title="双击重命名"
                      >
                        {s.title}
                      </span>
                      {isStreaming && (
                        <span className="shrink-0 inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          if (s.session_id === activeSessionId) setSessionDropdownOpen(false);
                          setRenaming({ id: s.session_id, title: s.title });
                        }}
                        title="重命名"
                        className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center"
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); void removeChat(s.session_id); }}
                        title="删除"
                        className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-danger-500 hover:bg-danger-50 flex items-center justify-center"
                      >
                        <XIcon size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          {activeSession && !renaming && (
            <button
              onClick={() => setRenaming({ id: activeSession.session_id, title: activeSession.title })}
              title="重命名当前会话"
              className="shrink-0 w-9 h-9 rounded-lg border border-stone-200 bg-white text-stone-500 hover:bg-stone-50 hover:text-primary-700 hover:border-primary-200 flex items-center justify-center"
            >
              <Pencil size={14} />
            </button>
          )}
          <button
            onClick={() => void newChat()}
            disabled={creating}
            title="新建一段会话"
            className="shrink-0 inline-flex items-center gap-1 px-3 h-9 rounded-lg border border-dashed border-stone-300 text-stone-600 hover:bg-stone-50 hover:border-primary-300 hover:text-primary-700 text-sm disabled:opacity-50"
          >
            <Plus size={14} />
            <span>新会话</span>
          </button>
        </div>
      )}

      {/* Messages */}
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-4 relative">
        {!activeSessionId && (
          <div className="absolute inset-0 flex items-center justify-center text-stone-400 px-6">
            <div className="text-center">
              <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
                <Sparkles size={18} />
              </div>
              <div className="text-sm text-stone-500 font-medium mb-1">
                {externalMode ? '先在左侧选择一项' : '该面试还没有会话'}
              </div>
              <div className="text-xs leading-relaxed">
                {externalMode ? '选中后会自动开始一段对话' : '点右上「+ 新会话」开始一段对话'}
              </div>
            </div>
          </div>
        )}
        {activeSessionId && messages.length === 0 && !streaming && (
          <div className="absolute inset-0 flex items-center justify-center text-stone-400 px-6">
            <div className="text-center">
              <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
                <Sparkles size={18} />
              </div>
              <div className="text-sm text-stone-500 font-medium mb-1">说点什么开始对话</div>
              <div className="text-xs leading-relaxed">输入消息后会看到流式生成的回答</div>
            </div>
          </div>
        )}
        <div style={{ height: messageVirtualizer.getTotalSize() }} className="relative">
          {messageVirtualizer.getVirtualItems().map((vi) => {
            const m = messages[vi.index];
            return (
              <div
                key={vi.key}
                ref={messageVirtualizer.measureElement}
                data-index={vi.index}
                style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)` }}
              >
                <div className="pb-3">
                  <Bubble role={m.role} content={m.content} />
                </div>
              </div>
            );
          })}
        </div>
        {streaming && !hidePartialBar && (
          <div className="flex justify-start">
            <div className="max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65] bg-stone-50 border border-stone-200 rounded-2xl">
              {partial ? <MarkdownBody source={partial} /> : (
                <span className="text-stone-400 inline-flex items-center gap-1.5">
                  <Spinner size={10} className="text-primary-500" />
                  {statusHint || 'AI 正在生成…'}
                </span>
              )}
              <button
                onClick={() => { if (activeRuntime) { activeRuntime.hidePartialBar = true; bump(); } }}
                className="ml-2 text-[11px] text-stone-400 hover:text-stone-600"
              >
                收起
              </button>
            </div>
          </div>
        )}
        {streaming && hidePartialBar && (
          <div className="flex justify-start">
            <button
              onClick={() => { if (activeRuntime) { activeRuntime.hidePartialBar = false; bump(); } }}
              className="rounded-full bg-primary-50 text-primary-700 text-xs px-3 py-1 inline-flex items-center gap-1.5 hover:bg-primary-100 border border-primary-100"
              title="展开流式生成"
            >
              <Spinner size={10} className="text-primary-500" />
              {statusHint || 'AI 正在后台生成…'} · 点击展开
            </button>
          </div>
        )}
      </div>

      {/* Bottom toolbar */}
      <div className="p-3 border-t border-stone-200">
        <div className="flex items-center gap-1.5 mb-2">
          <button
            onClick={() => setMode((m) => (m === 'AGENT' ? 'CHAT' : 'AGENT'))}
            className={[
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium tracking-wider',
              mode === 'AGENT'
                ? 'bg-primary-50 border-primary-200 text-primary-700'
                : 'bg-white border-stone-200 text-stone-600',
            ].join(' ')}
          >
            <span className={[
              'w-1.5 h-1.5 rounded-full',
              mode === 'AGENT' ? 'bg-primary-500' : 'bg-stone-400',
            ].join(' ')} />
            {mode === 'AGENT' ? <><Bot size={11} /> AGENT</> : <><MessageSquare size={11} /> CHAT</>}
          </button>
          <button
            onClick={toggleRecall}
            disabled={!activeSessionId || togglingRecall}
            title={recallEnabled ? '关闭记忆召回' : '开启记忆召回'}
            className={[
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-medium tracking-wider disabled:opacity-50',
              recallEnabled
                ? 'bg-accent-50 border-accent-200 text-accent-700'
                : 'bg-white border-stone-200 text-stone-600',
            ].join(' ')}
          >
            <Brain size={11} />
            {recallEnabled ? '记忆 · 开' : '记忆 · 关'}
          </button>
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files && e.target.files.length > 0) onAttachFiles(e.target.files);
              e.target.value = '';
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="p-1.5 text-stone-500 hover:text-stone-700 disabled:opacity-50"
            title="附加文件"
          >
            {uploading ? <Spinner size={12} /> : <Paperclip size={14} />}
          </button>
          <span className="text-[11px] text-stone-400 truncate flex-1">
            {attachments.length > 0
              ? attachments.map((a) => a.filename).join(' · ')
              : '点 📎 附加简历 / 文档'}
          </span>
          {attachments.length > 0 && (
            <button
              onClick={() => setAttachments([])}
              className="text-[11px] text-stone-400 hover:text-danger-500"
            >
              清空
            </button>
          )}
        </div>
        <div className="flex items-end gap-1.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            disabled={!activeSessionId || streaming}
            placeholder={
              activeSessionId
                ? '问点什么 · Shift+Enter 换行'
                : (externalMode ? '先在左侧选择' : '点右上 + 新建一段会话')
            }
            rows={2}
            className="flex-1 resize-none border border-stone-200 rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary-300 bg-stone-50 text-stone-800 disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={!activeSessionId || !input.trim() || streaming}
            className="w-9 h-9 rounded-lg bg-primary-500 text-white hover:bg-primary-600 flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {streaming ? <Check size={14} /> : <Send size={14} />}
          </button>
        </div>
      </div>
    </aside>
  );
}

function Bubble({ role, content }: { role: UIMessage['role']; content: string }) {
  const mine = role === 'user';
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65]',
          mine
            ? 'bg-primary-500 text-white rounded-2xl rounded-br-sm'
            : role === 'system'
              ? 'bg-warning-50 text-warning-700 border border-warning-200 rounded-2xl'
              : 'bg-stone-50 text-stone-800 border border-stone-200 rounded-2xl rounded-bl-sm',
        ].join(' ')}
      >
        {mine ? <span className="whitespace-pre-wrap">{content}</span> : <MarkdownBody source={content} />}
      </div>
    </div>
  );
}
