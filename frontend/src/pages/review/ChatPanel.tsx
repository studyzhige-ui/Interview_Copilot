import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Send,
  Paperclip,
  Bot,
  MessageSquare,
  Sparkles,
  ChevronDown,
  Plus,
  Pencil,
  X as XIcon,
  Check,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  createChatSession,
  deleteChatSession,
  getChatHistory,
  listChatSessions,
  renameChatSession,
} from '@/api/chat';
import { uploadKnowledgeFile } from '@/api/knowledge';
import { getModelsRuntime, updateModelsRuntime, getModelsCatalog } from '@/api/models';
import { tokenStore } from '@/lib/token';
import type { ChatMessageItem, ChatSessionListItem, ModelProfile, ModelRole, WSEvent } from '@/types/api';

interface Props {
  /** Real InterviewRecord id, or null for unscoped general chat. */
  interviewId: string | null;
  /** Title of the currently selected interview record (for header subtitle). */
  interviewTitle: string | null;
  width?: number;
}

interface UIMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

interface Attachment {
  doc_id: string;
  filename: string;
}

type Mode = 'CHAT' | 'AGENT';

interface SessionRuntime {
  ws: WebSocket | null;
  messages: UIMessage[];
  partial: string;       // streaming buffer (assistant response — content chunks only)
  status: string;        // latest [status] hint from the backend (e.g. "正在生成回答…")
  streaming: boolean;    // true while WS hasn't sent {type: done}
  hidePartialBar: boolean; // user dismissed the in-flight bubble for this round
  loadedHistory: boolean;
}

function toUI(m: ChatMessageItem): UIMessage {
  return {
    role: m.role === 'user' ? 'user' : m.role === 'assistant' ? 'assistant' : 'system',
    content: m.content,
  };
}

function wsUrlFor(sessionId: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const token = tokenStore.getAccess() ?? '';
  return `${proto}://${window.location.host}/api/v1/chat/ws/${encodeURIComponent(sessionId)}?token=${encodeURIComponent(token)}`;
}

export function ChatPanel({ interviewId, interviewTitle, width = 400 }: Props) {
  const [sessions, setSessions] = useState<ChatSessionListItem[]>([]);
  const [activeSession, setActiveSession] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<Mode>('CHAT');
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [modelName, setModelName] = useState('DeepSeek V4 Flash');
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [primaryId, setPrimaryId] = useState<string>('');
  const listRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  // Force-focus the rename input whenever a rename starts. `autoFocus` alone
  // can fail when React reuses the chip row's element across re-renders —
  // explicitly focusing here also selects the text so the user can just type
  // over it without having to click in first.
  useEffect(() => {
    if (renaming) {
      // RAF defers focus to after React has committed the input into the DOM.
      requestAnimationFrame(() => {
        renameInputRef.current?.focus();
        renameInputRef.current?.select();
      });
    }
  }, [renaming]);

  // ── Per-session runtime (messages + WS + partial) kept across switches ──
  const runtimes = useRef<Map<string, SessionRuntime>>(new Map());
  // tick is bumped whenever we want React to re-read from runtimes.
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((n) => n + 1), []);

  const getRuntime = useCallback((id: string): SessionRuntime => {
    let r = runtimes.current.get(id);
    if (!r) {
      r = {
        ws: null, messages: [], partial: '', status: '',
        streaming: false, hidePartialBar: false, loadedHistory: false,
      };
      runtimes.current.set(id, r);
    }
    return r;
  }, []);

  // Open (or return existing) WS for a session.
  const ensureWS = useCallback((id: string): WebSocket => {
    const r = getRuntime(id);
    if (r.ws && (r.ws.readyState === WebSocket.OPEN || r.ws.readyState === WebSocket.CONNECTING)) {
      return r.ws;
    }
    const ws = new WebSocket(wsUrlFor(id));
    r.ws = ws;
    ws.onmessage = (e) => {
      let evt: WSEvent;
      try { evt = JSON.parse(e.data); } catch { return; }
      const rt = getRuntime(id);
      if (evt.type === 'status') {
        // Pipeline progress hint; show in the in-flight bubble but never
        // store in the final assistant message.
        rt.status = evt.content;
        rt.streaming = true;
        bump();
      } else if (evt.type === 'chunk') {
        rt.partial += evt.content;
        rt.streaming = true;
        bump();
      } else if (evt.type === 'done') {
        if (rt.partial.trim()) {
          rt.messages.push({ role: 'assistant', content: rt.partial });
        }
        rt.partial = '';
        rt.status = '';
        rt.streaming = false;
        rt.hidePartialBar = false;
        bump();
      }
    };
    ws.onclose = () => {
      const rt = getRuntime(id);
      // If we still had buffered partial content when WS closed, persist it
      // as a system note so the user knows something arrived but the stream
      // got cut off (server crash, network drop, etc.).
      if (rt.partial) {
        rt.messages.push({ role: 'system', content: `（连接中断，已接收: ${rt.partial.slice(0, 200)}…）` });
        rt.partial = '';
      }
      rt.streaming = false;
      rt.ws = null;
      bump();
    };
    ws.onerror = () => { /* surfaced via onclose */ };
    return ws;
  }, [bump, getRuntime]);

  // Lazy-load history for a session the first time it's activated.
  useEffect(() => {
    if (!activeSession) return;
    const r = getRuntime(activeSession);
    if (r.loadedHistory) return;
    r.loadedHistory = true;
    getChatHistory(activeSession, 0, 100)
      .then((rows) => {
        const existing = getRuntime(activeSession);
        // Only inject from-history if we haven't sent anything yet; otherwise
        // history may collide with locally-appended messages.
        if (existing.messages.length === 0) {
          existing.messages = rows.map(toUI);
        }
        bump();
      })
      .catch(() => { /* ignore — empty session view is fine */ });
  }, [activeSession, getRuntime, bump]);

  // Cleanup all WSes on ChatPanel unmount.
  useEffect(() => {
    const map = runtimes.current;
    return () => { map.forEach((r) => r.ws?.close()); };
  }, []);

  // Load model info once.
  useEffect(() => {
    getModelsRuntime()
      .then((rt) => {
        const resolved = rt.resolved?.primary;
        if (resolved) {
          setModelName(resolved.display_name);
          setPrimaryId(resolved.profile_id);
        }
      })
      .catch(() => {});
    getModelsCatalog()
      .then((c) => setProfiles(c.profiles))
      .catch(() => {});
  }, []);

  // Close model dropdown / session dropdown on outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!modelRef.current?.contains(e.target as Node)) setModelOpen(false);
      if (!sessionRef.current?.contains(e.target as Node)) setSessionDropdownOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  // Refetch session list when scope (interviewId) changes.
  useEffect(() => {
    let alive = true;
    const q = interviewId
      ? { session_type: 'debrief', interview_id: interviewId }
      : { session_type: 'general' };
    listChatSessions(q)
      .then(async (rows) => {
        if (!alive) return;
        setSessions(rows);
        if (rows.length > 0) {
          setActiveSession(rows[0].session_id);
          return;
        }
        if (interviewId) {
          try {
            const created = await createChatSession({
              session_type: 'debrief',
              interview_id: interviewId,
              title: '复盘对话 1',
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
            setActiveSession(created.session_id);
          } catch (e) {
            if (alive) toast.error(extractErr(e, '自动创建对话失败'));
          }
        } else {
          setActiveSession(null);
        }
      })
      .catch((e) => alive && toast.error(extractErr(e, '对话列表加载失败')));
    return () => { alive = false; };
  }, [interviewId]);

  // Auto-scroll on new content for the active session.
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [tick, activeSession]);

  const newChat = async () => {
    setCreating(true);
    try {
      const payload = interviewId
        ? { session_type: 'debrief' as const, interview_id: interviewId, title: `对话 ${sessions.length + 1}` }
        : { session_type: 'general' as const, title: `对话 ${sessions.length + 1}` };
      const created = await createChatSession(payload);
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
      setActiveSession(created.session_id);
      setSessionDropdownOpen(false);
    } catch (e) {
      toast.error(extractErr(e, '创建对话失败'));
    } finally {
      setCreating(false);
    }
  };

  const removeChat = async (id: string) => {
    try {
      await deleteChatSession(id);
      // Close that session's WS and drop its runtime.
      const r = runtimes.current.get(id);
      r?.ws?.close();
      runtimes.current.delete(id);
      setSessions((s) => {
        const next = s.filter((x) => x.session_id !== id);
        if (activeSession === id) setActiveSession(next[0]?.session_id ?? null);
        return next;
      });
    } catch (e) {
      toast.error(extractErr(e, '删除对话失败'));
    }
  };

  const commitRename = async () => {
    if (!renaming) return;
    const title = renaming.title.trim();
    if (!title) { setRenaming(null); return; }
    try {
      await renameChatSession(renaming.id, title);
      setSessions((s) => s.map((x) => x.session_id === renaming.id ? { ...x, title } : x));
    } catch (e) {
      toast.error(extractErr(e, '重命名失败'));
    }
    setRenaming(null);
  };

  const onAttachFiles = async (files: FileList) => {
    setUploading(true);
    const added: Attachment[] = [];
    for (const f of Array.from(files)) {
      try {
        const doc = await uploadKnowledgeFile(f, { category: 'chat_attachment', source_type: 'official_docs' });
        added.push({ doc_id: doc.id, filename: f.name });
      } catch {
        toast.error(`附件上传失败：${f.name}`);
      }
    }
    if (added.length > 0) {
      setAttachments((arr) => [...arr, ...added]);
      toast.success(`已附加 ${added.length} 个文件`);
    }
    setUploading(false);
  };

  const send = () => {
    const text = input.trim();
    if (!text || !activeSession) return;
    const r = getRuntime(activeSession);
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
    const ws = ensureWS(activeSession);
    const trySend = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ message: payload }));
      } else if (ws.readyState === WebSocket.CONNECTING) {
        // Defer until open
        ws.addEventListener('open', () => ws.send(JSON.stringify({ message: payload })), { once: true });
      } else {
        // Already closed; spawn a fresh WS and retry once.
        const fresh = ensureWS(activeSession);
        fresh.addEventListener('open', () => fresh.send(JSON.stringify({ message: payload })), { once: true });
      }
    };
    trySend();
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const onPickModel = async (p: ModelProfile) => {
    if (!p.ready) {
      toast.warn(`需先配置 ${p.api_key_env}`);
      return;
    }
    setModelOpen(false);
    setModelName(p.display_name);
    setPrimaryId(p.id);
    try {
      const patch: Partial<Record<ModelRole, string>> = { primary: p.id };
      await updateModelsRuntime(patch);
      toast.success(`已切换为 ${p.display_name}`);
    } catch {
      toast.error('切换模型失败');
    }
  };

  // ── Derived for render ──────────────────────────────────────────────────
  const subtitle = interviewId ? interviewTitle ?? '基于本次记录' : '通用对话（未绑定面试）';
  const activeRuntime = activeSession ? getRuntime(activeSession) : null;
  const messages = activeRuntime?.messages ?? [];
  const partial = activeRuntime?.partial ?? '';
  const statusHint = activeRuntime?.status ?? '';
  const streaming = !!activeRuntime?.streaming;
  const hidePartialBar = !!activeRuntime?.hidePartialBar;
  const activeSessionTitle = sessions.find((s) => s.session_id === activeSession)?.title ?? '选择对话';

  // Sessions with background-streaming activity (to show dots in dropdown).
  const streamingSessionIds = useMemo(() => {
    const set = new Set<string>();
    runtimes.current.forEach((r, id) => { if (r.streaming) set.add(id); });
    return set;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  return (
    <aside
      style={{ width }}
      className="shrink-0 bg-white border-l border-stone-200 flex flex-col"
    >
      {/* Header: title + (+ 新对话) + model selector */}
      <div className="px-4 pt-4 pb-2.5 flex items-start justify-between gap-2 border-b border-stone-100">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-stone-800">复盘对话</div>
          <div className="text-xs text-stone-500 mt-0.5 truncate">{subtitle}</div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={newChat}
            disabled={creating}
            title="新对话"
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-dashed border-stone-300 text-stone-600 hover:bg-stone-50 hover:border-primary-300 hover:text-primary-700 text-sm disabled:opacity-50"
          >
            <Plus size={13} />
            <span>新对话</span>
          </button>
          <div ref={modelRef} className="relative">
            <button
              onClick={() => setModelOpen(!modelOpen)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-stone-200 bg-stone-50 text-stone-700 text-xs hover:bg-stone-100 font-mono"
            >
              <Sparkles size={12} className="text-accent-700" />
              <span className="truncate max-w-[100px]">{modelName}</span>
              <ChevronDown size={12} className="text-stone-400" />
            </button>
            {modelOpen && (
              <div className="absolute top-full right-0 mt-1 w-[240px] max-h-[320px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
                {profiles.length === 0 && (
                  <div className="px-2.5 py-2 text-xs text-stone-400">载入中…</div>
                )}
                {profiles.map((p) => {
                  const sel = p.id === primaryId;
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
      </div>

      {/* Session switcher — dropdown list (replaces chip row) */}
      <div className="px-3 py-2 border-b border-stone-200">
        <div ref={sessionRef} className="relative">
          <button
            onClick={() => setSessionDropdownOpen((v) => !v)}
            className="w-full inline-flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-700 text-sm"
          >
            <span className="flex items-center gap-2 min-w-0">
              <MessageSquare size={13} className="text-stone-500 shrink-0" />
              <span className="truncate">{activeSession ? activeSessionTitle : '尚无对话'}</span>
              {streaming && (
                <span className="shrink-0 inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
              )}
            </span>
            <ChevronDown size={14} className={[
              'text-stone-400 transition-transform',
              sessionDropdownOpen ? 'rotate-180' : '',
            ].join(' ')} />
          </button>
          {sessionDropdownOpen && (
            <div className="absolute left-0 right-0 top-full mt-1 max-h-[320px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
              {sessions.length === 0 && (
                <div className="px-3 py-3 text-sm text-stone-400 text-center">还没有对话，点右上「+ 新对话」</div>
              )}
              {sessions.map((s) => {
                const act = s.session_id === activeSession;
                const isEditing = renaming?.id === s.session_id;
                const isStreaming = streamingSessionIds.has(s.session_id);
                return (
                  <div
                    key={s.session_id}
                    className={[
                      'group flex items-center gap-2 px-2.5 py-1.5 rounded-md cursor-pointer',
                      act ? 'bg-primary-50' : 'hover:bg-stone-50',
                    ].join(' ')}
                  >
                    {isEditing ? (
                      <input
                        ref={renameInputRef}
                        autoFocus
                        value={renaming!.title}
                        onChange={(e) => setRenaming({ id: s.session_id, title: e.target.value })}
                        onBlur={() => { void commitRename(); }}
                        onClick={(e) => e.stopPropagation()}
                        onKeyDown={(e) => {
                          e.stopPropagation();
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            void commitRename();
                          } else if (e.key === 'Escape') {
                            e.preventDefault();
                            setRenaming(null);
                          }
                        }}
                        placeholder="按 Enter 保存，Esc 取消"
                        className="flex-1 min-w-0 text-sm px-2 py-1 border border-primary-300 rounded outline-none focus:ring-2 focus:ring-primary-200"
                      />
                    ) : (
                      <>
                        <span
                          onClick={() => { setActiveSession(s.session_id); setSessionDropdownOpen(false); }}
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
                          onClick={(e) => { e.stopPropagation(); setRenaming({ id: s.session_id, title: s.title }); }}
                          title="重命名"
                          className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center"
                        >
                          <Pencil size={12} />
                        </button>
                        {sessions.length > 1 && (
                          <button
                            onClick={(e) => { e.stopPropagation(); removeChat(s.session_id); }}
                            title="删除"
                            className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-danger-500 hover:bg-danger-50 flex items-center justify-center"
                          >
                            <XIcon size={12} />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-3 relative">
        {!activeSession && (
          <div className="m-auto text-center text-stone-400 px-6">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-sm text-stone-500 font-medium mb-1">点 + 开始一段对话</div>
            <div className="text-xs leading-relaxed">
              {interviewId ? '上传解析完成后会自动给出复盘建议' : '不绑定面试也可以使用通用对话'}
            </div>
          </div>
        )}
        {activeSession && messages.length === 0 && !streaming && (
          <div className="m-auto text-center text-stone-400 px-6">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-sm text-stone-500 font-medium mb-1">
              {interviewId ? '上传解析完成后会自动给出复盘建议' : '说点什么开始对话'}
            </div>
            <div className="text-xs leading-relaxed">输入消息后会看到流式生成的回答</div>
          </div>
        )}
        {messages.map((m, i) => <Bubble key={i} role={m.role} content={m.content} />)}

        {/* In-flight streaming bubble — lives INSIDE the conversation, where
         *  the final assistant reply will eventually appear. Disappears the
         *  moment the WS sends {type:'done'} and the real assistant Bubble
         *  takes its place. Status hints (e.g. "正在生成回答…") show on top of
         *  the partial content but are NOT persisted into the final message. */}
        {streaming && !hidePartialBar && (
          <div className="flex justify-start">
            <div className="max-w-[85%] bg-stone-100/70 backdrop-blur border border-stone-200 rounded-[14px] rounded-bl-[4px] px-3.5 py-2.5 relative">
              <button
                onClick={() => { if (activeRuntime) { activeRuntime.hidePartialBar = true; bump(); } }}
                className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-white border border-stone-200 text-stone-400 hover:text-stone-600 hover:bg-stone-50 inline-flex items-center justify-center shadow-sm"
                title="隐藏（后台继续生成）"
              >
                <XIcon size={11} />
              </button>
              <div className="flex items-center gap-1.5 text-[11px] text-primary-600 mb-1">
                <Spinner size={10} className="text-primary-500" />
                <span className="font-medium">{statusHint || 'AI 正在回答…'}</span>
              </div>
              {partial ? (
                <div className="text-[14px] text-stone-700 leading-[1.65] whitespace-pre-wrap">
                  {partial}
                  <span className="inline-block w-1.5 h-3 ml-0.5 bg-stone-400 animate-pulse align-middle" />
                </div>
              ) : (
                <div className="text-xs text-stone-400 italic">准备中…</div>
              )}
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

      {/* Toolbar */}
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
            disabled={!activeSession || streaming}
            placeholder={
              activeSession
                ? '问点什么 · Shift+Enter 换行'
                : '先点 + 新建一段对话'
            }
            rows={2}
            className="flex-1 resize-none border border-stone-200 rounded-lg px-3 py-2 text-[13px] outline-none focus:border-primary-300 bg-stone-50 text-stone-800 disabled:opacity-50"
          />
          <button
            onClick={send}
            disabled={!activeSession || !input.trim() || streaming}
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
          'max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65] whitespace-pre-wrap',
          mine
            ? 'bg-primary-500 text-white rounded-[14px] rounded-br-[4px]'
            : role === 'system'
            ? 'bg-warning-50 text-warning-700 rounded-[14px] text-xs italic'
            : 'bg-stone-100 text-stone-800 rounded-[14px] rounded-bl-[4px]',
        ].join(' ')}
      >
        {content}
      </div>
    </div>
  );
}
