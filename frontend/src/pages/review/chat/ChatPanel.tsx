/**
 * ChatPanel — the right-pane chat UI (composition shell).
 *
 * Two scope shapes:
 *
 *  1. **Review (debrief) mode** — caller passes ``interviewId``. The panel
 *     fetches its own session list (``type='debrief', subject_id``)
 *     and renders a dropdown for new / rename / delete + active-session
 *     selection. Auto-selects the most recent session; auto-creates
 *     "会话 1" the first time the user opens a record with no sessions.
 *
 *  2. **External mode** — caller passes ``sessionId`` directly (used by
 *     ``GeneralChatPage`` where the left sidebar already owns the session
 *     list). The dropdown / CRUD UI is hidden; ChatPanel just renders
 *     the chat for whatever sessionId was handed in.
 *
 * The transport is SSE (``streamChatTurn``). Mock-style WebSocket has been
 * removed — see ``app/api/chat/streaming.py`` for the rationale (GPT /
 * Claude / Gemini all use SSE for one-way text).
 *
 * The pieces live one-per-file in this directory:
 *   useSessionRuntimes      per-session SSE runtime LRU + render ticks
 *   useChatStream           send / cancel — the SSE event pipeline
 *   useSessionList          internal-mode session list + CRUD
 *   usePersistedSessionState  localStorage draft + CHAT/AGENT mode
 *   useGlobalMemoryToggle   per-session memory-recall switch
 *   useChatModels           model picker (React Query, shares keys with
 *                           the Models page)
 *   MessageList / Bubble / MessageBlocks / SessionDropdown / ChatToolbar
 */

import { useEffect, useRef, useState } from 'react';
import { Sparkles, ChevronDown } from 'lucide-react';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { getChatTranscript } from '@/api/chat';
import type { Attachment } from './types';
import { toUI } from './types';
import { useSessionRuntimes } from './useSessionRuntimes';
import { useChatStream } from './useChatStream';
import { useSessionList } from './useSessionList';
import { useSessionDraft, useSessionMode } from './usePersistedSessionState';
import { useGlobalMemoryToggle } from './useGlobalMemoryToggle';
import { useChatModels } from './useChatModels';
import { MessageList } from './MessageList';
import { SessionDropdown } from './SessionDropdown';
import { ChatToolbar } from './ChatToolbar';

interface Props {
  /** Review/debrief mode: bind to this interview record. ChatPanel will
   *  maintain its own session list filtered by (type=debrief,
   *  subject_id=interviewId). Mutually exclusive with ``sessionId``. */
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

  // ── Runtime cache + session list ─────────────────────────────────────
  const { tick, bump, getRuntime, dropRuntime, streamingSet } = useSessionRuntimes();
  const sessionList = useSessionList({
    externalMode,
    interviewId,
    sessionType,
    onSessionDeleted: dropRuntime,
  });

  // The active session id either comes straight from the prop (external)
  // or from our internal list state.
  const activeSessionId = externalMode ? externalSessionId : sessionList.internalActiveId;

  // ── Input / mode / attachments / memory / models ─────────────────────
  const { input, setInput } = useSessionDraft(activeSessionId);
  const serverMode = sessionList.sessions.find(
    (s) => s.session_id === activeSessionId,
  )?.mode;
  const { mode, setMode } = useSessionMode(activeSessionId, serverMode);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const { globalMemoryOn, togglingMemory, toggleGlobalMemory } =
    useGlobalMemoryToggle(activeSessionId);
  const { profiles, activeProfileId, activeModelName, pickModel } =
    useChatModels(mode);
  const { sendMessage, resumeTurn, cancel } = useChatStream({
    activeSessionId, getRuntime, bump, mode,
  });

  // ── Refs + dropdown-close-on-outside-click ───────────────────────────
  const listRef = useRef<HTMLDivElement | null>(null);
  const modelRef = useRef<HTMLDivElement | null>(null);
  const sessionDropdownRef = useRef<HTMLDivElement | null>(null);
  const [modelOpen, setModelOpen] = useState(false);
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!modelRef.current?.contains(e.target as Node)) setModelOpen(false);
      if (!sessionDropdownRef.current?.contains(e.target as Node)) setSessionDropdownOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  // ── Lazy-load transcript for the active session ──────────────────────
  // The block-aware transcript replays agent tool-call cards.
  useEffect(() => {
    if (!activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.loadedHistory) return;
    // Abort the in-flight transcript fetch on session switch so a
    // late response from session A can't stomp on session B's
    // runtime entry, and the backend stops materialising the
    // (now-unused) transcript.
    const controller = new AbortController();
    let alive = true;
    getChatTranscript(activeSessionId, { signal: controller.signal })
      .then((resp) => {
        if (!alive) return;
        const rt = getRuntime(activeSessionId);
        if (rt.messages.length === 0) rt.messages = resp.messages.map(toUI);
        rt.loadedHistory = true;
        bump();
        if (resp.active_turn_id && !rt.streaming) resumeTurn(resp.active_turn_id);
      })
      .catch(() => { /* empty / fresh session OR aborted on switch — both fine */ });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [activeSessionId, getRuntime, bump, resumeTurn]);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [tick, activeSessionId]);

  // ── Send: compose payload from input + attachments ───────────────────
  const send = () => {
    const text = input.trim();
    if (!text || !activeSessionId) return;
    const runtime = getRuntime(activeSessionId);
    if (runtime.streaming || runtime.turnId) return;
    let payload = text;
    if (attachments.length > 0) {
      const tail = attachments.map((a) => `[附件: ${a.filename} (doc=${a.doc_id})]`).join('\n');
      payload = `${tail}\n\n${text}`;
    }
    setInput('');
    setAttachments([]);
    sendMessage(payload);
  };

  // ── Derived render state ────────────────────────────────────────────
  const subtitle = sessionTitle ?? '复盘对话';
  const activeRuntime = activeSessionId ? getRuntime(activeSessionId) : null;
  const messages = activeRuntime?.messages ?? [];
  const partial = activeRuntime?.partial ?? '';
  const inflightBlocks = activeRuntime?.inflightBlocks ?? [];
  const inflightSources = activeRuntime?.inflightSources ?? [];
  const statusHint = activeRuntime?.status ?? '';
  const streaming = !!activeRuntime?.streaming;
  const hidePartialBar = !!activeRuntime?.hidePartialBar;
  const activeSession = sessionList.sessions.find((s) => s.session_id === activeSessionId);
  const activeSessionTitle = activeSession?.title ?? '选择会话';

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
            title="当前回答模型"
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-stone-200 bg-stone-50 text-stone-700 text-xs hover:bg-stone-100 font-mono"
          >
            <Sparkles size={12} className="text-accent-700" />
            <span className="truncate max-w-[100px]">{activeModelName}</span>
            <ChevronDown size={12} className="text-stone-400" />
          </button>
          {modelOpen && (
            <div className="absolute top-full right-0 mt-1 w-[260px] max-h-[340px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
              <div className="px-2.5 py-1.5 text-[11px] text-stone-500 border-b border-stone-100 mb-1">
                选择回答模型{mode === 'AGENT' ? '（Agent 模式需支持工具调用）' : ''}
              </div>
              {profiles.length === 0 && <div className="px-2.5 py-2 text-xs text-stone-400">载入中…</div>}
              {profiles
                .filter((p) => mode !== 'AGENT' || p.supports_function_calling)
                .map((p) => {
                  const sel = p.id === activeProfileId;
                  return (
                    <div
                      key={p.id}
                      // Close only on a successful pick — a not-ready /
                      // unsupported model keeps the dropdown open (the
                      // warn toast explains why), same as pre-split.
                      onClick={() => { void pickModel(p).then((ok) => { if (ok) setModelOpen(false); }); }}
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
        <SessionDropdown
          sessions={sessionList.sessions}
          activeSessionId={activeSessionId}
          activeSessionTitle={activeSessionTitle}
          streaming={streaming}
          streamingSet={streamingSet}
          open={sessionDropdownOpen}
          setOpen={setSessionDropdownOpen}
          dropdownRef={sessionDropdownRef}
          onSelect={sessionList.setInternalActiveId}
          renaming={sessionList.renaming}
          setRenaming={sessionList.setRenaming}
          commitRename={sessionList.commitRename}
          creating={sessionList.creating}
          onNewChat={() => { void sessionList.newChat(); setSessionDropdownOpen(false); }}
          onRemoveChat={sessionList.removeChat}
        />
      )}

      {/* Messages */}
      <MessageList
        listRef={listRef}
        activeSessionId={activeSessionId}
        externalMode={externalMode}
        messages={messages}
        partial={partial}
        inflightBlocks={inflightBlocks}
        inflightSources={inflightSources}
        statusHint={statusHint}
        streaming={streaming}
        hidePartialBar={hidePartialBar}
        onTogglePartialBar={(hidden) => {
          if (!activeSessionId) return;
          getRuntime(activeSessionId).hidePartialBar = hidden;
          bump();
        }}
      />

      {/* Bottom toolbar */}
      <ChatToolbar
        activeSessionId={activeSessionId}
        externalMode={externalMode}
        mode={mode}
        setMode={setMode}
        globalMemoryOn={globalMemoryOn}
        togglingMemory={togglingMemory}
        onToggleGlobalMemory={() => { void toggleGlobalMemory(); }}
        input={input}
        setInput={setInput}
        streaming={streaming}
        onSend={send}
        onCancel={cancel}
        attachments={attachments}
        setAttachments={setAttachments}
      />

      {/* Styled delete confirmation — replaces the off-brand native
          window.confirm() that showed "Code" as its dialog title.
          Same ConfirmDialog component used by the Library page and
          the Memory tab, so the visual language stays consistent. */}
      <ConfirmDialog
        open={!!sessionList.pendingDelete}
        danger
        title="删除对话"
        description={
          sessionList.pendingDelete
            ? `确定删除「${sessionList.pendingDelete.title}」？该对话下的所有消息将被永久删除，不可恢复。`
            : ''
        }
        confirmText="删除"
        loading={sessionList.deletingChat}
        onConfirm={() => { void sessionList.confirmRemoveChat(); }}
        onCancel={() => { if (!sessionList.deletingChat) sessionList.setPendingDelete(null); }}
      />
    </aside>
  );
}
