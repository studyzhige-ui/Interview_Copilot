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
 *   useChatModels           model picker (React Query, shares keys with
 *                           the Models page)
 *   MessageList / Bubble / MessageBlocks / SessionDropdown / ChatToolbar
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import {
  getChatTranscript,
  getAgentTask,
  interruptChatTurnForSubmission,
  retryPendingSubmission,
  updatePendingSubmission,
  withdrawPendingSubmission,
} from '@/api/chat';
import type { PendingSubmissionItem, ProductObjectReference } from '@/types/api';
import type { Attachment, Mode } from './types';
import { toUI } from './types';
import { useSessionRuntimes } from './useSessionRuntimes';
import { useChatStream } from './useChatStream';
import { useSessionList } from './useSessionList';
import {
  useSessionDraft,
  useSessionMode,
} from './usePersistedSessionState';
import { useSessionExecutionMode } from './useSessionExecutionMode';
import { usePendingSubmissions } from './usePendingSubmissions';
import { useChatModels } from './useChatModels';
import { MessageList } from './MessageList';
import { SessionDropdown } from './SessionDropdown';
import { ChatToolbar } from './ChatToolbar';
import { InteractionCard } from './InteractionCard';
import { AttachmentSources } from './AttachmentSources';
import { AgentTaskCard } from './AgentTaskCard';
import { ConversationGuidanceButton } from './ConversationGuidanceButton';
import { ConversationMemoryControlsButton } from './ConversationMemoryControlsButton';

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
  className?: string;
  questionIndexes?: number[];
  onRemoveQuestion?: (index: number) => void;
  onClearQuestions?: () => void;
  /** Explicit user-visible product handoff for the next Send action only. */
  productObjectReferences?: ProductObjectReference[];
  onRemoveProductObjectReference?: (reference: ProductObjectReference) => void;
  onProductObjectReferencesConsumed?: () => void;
  /** Product runtimes with a single execution mode (currently Career Agent)
   *  can lock the strategy and remove the mode switch from the UI. */
  fixedMode?: Mode;
}

export function ChatPanel({
  interviewId,
  sessionId: externalSessionId,
  sessionTitle,
  sessionType = 'debrief',
  width = 400,
  flexible = false,
  className = '',
  questionIndexes = [],
  onRemoveQuestion = () => {},
  onClearQuestions = () => {},
  productObjectReferences = [],
  onRemoveProductObjectReference = () => {},
  onProductObjectReferencesConsumed,
  fixedMode,
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

  // ── Input / mode / attachments / models ──────────────────────────────
  const { input, setInput } = useSessionDraft(activeSessionId);
  const serverMode = sessionList.sessions.find(
    (s) => s.session_id === activeSessionId,
  )?.mode;
  const sessionMode = useSessionMode(activeSessionId, serverMode);
  const mode = fixedMode ?? sessionMode.mode;
  const serverExecutionMode = sessionList.sessions.find(
    (s) => s.session_id === activeSessionId,
  );
  const policyMode = useSessionExecutionMode(
    activeSessionId,
    serverExecutionMode
      ? {
          execution_mode: serverExecutionMode.execution_mode,
          execution_mode_version: serverExecutionMode.execution_mode_version,
        }
      : undefined,
  );
  const [attachmentState, setAttachmentState] = useState<{
    sessionId: string | null;
    items: Attachment[];
  }>({ sessionId: activeSessionId ?? null, items: [] });
  const attachments = attachmentState.sessionId === activeSessionId
    ? attachmentState.items
    : [];
  const setAttachments = useCallback<React.Dispatch<React.SetStateAction<Attachment[]>>>(
    (update) => {
      setAttachmentState((current) => {
        const currentItems = current.sessionId === activeSessionId ? current.items : [];
        return {
          sessionId: activeSessionId ?? null,
          items: typeof update === 'function' ? update(currentItems) : update,
        };
      });
    },
    [activeSessionId],
  );
  const { profiles, activeProfileId, activeModelName, pickModel } =
    useChatModels(mode);
  const [pendingRefreshToken, setPendingRefreshToken] = useState(0);
  const requestPendingRefresh = useCallback(
    () => setPendingRefreshToken((value) => value + 1),
    [],
  );
  const queryClient = useQueryClient();
  const refreshAgentTask = useCallback((targetSessionId: string, turnId: string) => {
    void queryClient.invalidateQueries({
      queryKey: ['chat', 'agent-task', targetSessionId, turnId],
    });
  }, [queryClient]);
  const { sendMessage, resumeTurn, cancel } = useChatStream({
    activeSessionId, getRuntime, bump, mode, executionMode: policyMode.executionMode,
    onQueueChanged: requestPendingRefresh,
    onAgentTaskChanged: refreshAgentTask,
    onObjectReferencesConsumed: onProductObjectReferencesConsumed,
  });
  const pending = usePendingSubmissions(activeSessionId, pendingRefreshToken);

  const updateQueuedSubmission = useCallback(async (
    submission: PendingSubmissionItem,
    update: Pick<PendingSubmissionItem, 'message' | 'mode' | 'execution_mode' | 'question_indexes' | 'attachments' | 'object_references'>,
  ) => {
    if (!activeSessionId) return;
    await updatePendingSubmission(activeSessionId, submission.submission_id, {
      expected_version: submission.version,
      ...update,
    });
    toast.success('已更新排队消息');
    requestPendingRefresh();
  }, [activeSessionId, requestPendingRefresh]);

  const withdrawQueuedSubmission = useCallback(async (submission: PendingSubmissionItem) => {
    if (!activeSessionId) return;
    await withdrawPendingSubmission(activeSessionId, submission.submission_id, submission.version);
    toast.success('已撤回排队消息');
    requestPendingRefresh();
  }, [activeSessionId, requestPendingRefresh]);

  const retryQueuedSubmission = useCallback(async (submission: PendingSubmissionItem) => {
    if (!activeSessionId) return;
    const admission = await retryPendingSubmission(
      activeSessionId,
      submission.submission_id,
      submission.version,
    );
    requestPendingRefresh();
    if (admission.status === 'admitted' && admission.turn_id) {
      resumeTurn(admission.turn_id);
      return;
    }
    if (admission.status === 'failed') {
      toast.error(admission.error ?? '重试未能通过发送校验，请编辑或撤回该消息');
      return;
    }
    toast.info('已请求重试，消息仍在队列中');
  }, [activeSessionId, requestPendingRefresh, resumeTurn]);

  const interruptForQueuedSubmission = useCallback(async (submission: PendingSubmissionItem) => {
    if (!activeSessionId) return;
    const turnId = getRuntime(activeSessionId).turnId;
    if (!turnId) throw new Error('当前没有可停止的任务');
    await interruptChatTurnForSubmission(
      activeSessionId,
      turnId,
      submission.submission_id,
      submission.version,
    );
    toast.info('正在安全停止当前任务，随后发送所选消息');
    requestPendingRefresh();
  }, [activeSessionId, getRuntime, requestPendingRefresh]);

  const removePendingSource = useCallback(async (
    submission: PendingSubmissionItem,
    sourceId: string,
  ) => {
    await updateQueuedSubmission(submission, {
      message: submission.message,
      mode: submission.mode,
      execution_mode: submission.execution_mode,
      question_indexes: submission.question_indexes,
      attachments: submission.attachments.filter((item) => item.draft_id !== sourceId),
      object_references: submission.object_references,
    });
  }, [updateQueuedSubmission]);

  // ── Refs + dropdown-close-on-outside-click ───────────────────────────
  const listRef = useRef<HTMLDivElement | null>(null);
  const sessionDropdownRef = useRef<HTMLDivElement | null>(null);
  const [sessionDropdownOpen, setSessionDropdownOpen] = useState(false);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
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

  // A queued submission disappears from the projection when the backend
  // claims it. Re-read the authoritative transcript and subscribe only when
  // that projection exposes a real active turn id.
  const pendingSnapshotRef = useRef<{
    sessionId: string | null;
    loaded: boolean;
    ids: Set<string>;
  }>({ sessionId: null, loaded: false, ids: new Set() });
  useEffect(() => {
    if (!activeSessionId || !pending.loaded) return;
    const previous = pendingSnapshotRef.current;
    const currentIds = new Set(pending.items.map((item) => item.submission_id));
    const sameSession = previous.sessionId === activeSessionId;
    const claimed = sameSession && previous.loaded
      && [...previous.ids].some((id) => !currentIds.has(id));
    pendingSnapshotRef.current = {
      sessionId: activeSessionId,
      loaded: true,
      ids: currentIds,
    };
    if (!claimed) return;

    const controller = new AbortController();
    getChatTranscript(activeSessionId, { signal: controller.signal })
      .then((resp) => {
        const runtime = getRuntime(activeSessionId);
        if (runtime.streaming || runtime.turnId) return;
        runtime.messages = resp.messages.map(toUI);
        runtime.loadedHistory = true;
        bump();
        if (resp.active_turn_id) resumeTurn(resp.active_turn_id);
      })
      .catch(() => { /* next projection refresh or page reload can recover */ });
    return () => controller.abort();
  }, [activeSessionId, pending.items, pending.loaded, getRuntime, bump, resumeTurn]);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [tick, activeSessionId]);

  // ── Send structured turn input ──────────────────────────────────────
  const send = () => {
    const text = input.trim();
    if (!text || !activeSessionId) return;
    const runtime = getRuntime(activeSessionId);
    if (runtime.streaming || runtime.turnId) return;
    if (attachments.some((attachment) => (
      attachment.status === 'uploading' || attachment.status === 'failed'
    ))) return;
    const turnAttachments = attachments;
    setInput('');
    setAttachments([]);
    sendMessage(text, questionIndexes, turnAttachments, productObjectReferences);
    onClearQuestions();
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
  const interaction = activeRuntime?.interaction ?? null;
  const activeTurnId = activeRuntime?.turnId ?? null;
  const agentTaskQuery = useQuery({
    queryKey: ['chat', 'agent-task', activeSessionId, activeTurnId],
    queryFn: ({ signal }) => getAgentTask(activeSessionId!, activeTurnId!, { signal }),
    enabled: Boolean(activeSessionId && activeTurnId),
    // AgentTask updates are durable but do not add a second SSE event stream.
    // Poll only while execution is moving; waiting/reload gets one canonical read.
    refetchInterval: streaming ? 1_500 : false,
    staleTime: 500,
  });
  const disconnectedTurnId = !streaming && !interaction
    ? activeRuntime?.turnId ?? null
    : null;
  const hidePartialBar = !!activeRuntime?.hidePartialBar;
  const activeSession = sessionList.sessions.find((s) => s.session_id === activeSessionId);
  const activeSessionTitle = activeSession?.title ?? '选择会话';

  // ────────────────────────────────────────────────────────────────────
  return (
    <aside
      style={flexible ? undefined : { '--chat-panel-width': `${width}px` } as CSSProperties}
      className={[
        'bg-white border-l border-stone-200 flex flex-col',
        flexible ? 'flex-1 min-w-0' : 'w-full lg:w-[var(--chat-panel-width)] shrink-0',
        className,
      ].join(' ')}
    >
      {/* Row 1: conversation identity; model and approval controls live in the Composer. */}
      <div className="px-4 pt-4 pb-2.5 flex items-center justify-between gap-2 border-b border-stone-100">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-stone-800 truncate">{subtitle}</div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {disconnectedTurnId && (
            <button
              onClick={() => resumeTurn(disconnectedTurnId)}
              className="px-2.5 py-1 rounded-lg border border-warning-200 bg-warning-50 text-warning-700 text-xs hover:bg-warning-100"
              title="服务器任务仍在运行，重新订阅其输出"
            >
              重新连接
            </button>
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

      <div className="flex shrink-0 justify-end gap-2 border-b border-stone-100 bg-white px-3 py-1.5">
        <ConversationMemoryControlsButton sessionId={activeSessionId} />
        <ConversationGuidanceButton sessionId={activeSessionId} />
      </div>

      {/* Messages */}
      <MessageList
        listRef={listRef}
        activeSessionId={activeSessionId}
        activeTurnId={activeTurnId}
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

      {activeSessionId && (
        <AttachmentSources
          sessionId={activeSessionId}
          interviewId={interviewId}
          pendingSubmissions={pending.items}
          refreshKey={[
            activeRuntime?.turnId ?? '',
            messages.length,
            pending.items.map((item) => `${item.submission_id}:${item.version}`).join('|'),
          ].join(':')}
          onRemovePendingSource={removePendingSource}
        />
      )}

      {agentTaskQuery.data && <AgentTaskCard task={agentTaskQuery.data} />}

      {activeSessionId && activeRuntime?.turnId && interaction && (
        <InteractionCard
          sessionId={activeSessionId}
          turnId={activeRuntime.turnId}
          interaction={interaction}
          onResolved={(cancelled) => {
            const runtime = getRuntime(activeSessionId);
            runtime.interaction = null;
            runtime.inflightBlocks = [];
            runtime.inflightSources = [];
            runtime.partial = '';
            if (cancelled) {
              runtime.turnId = null;
              runtime.status = '';
              bump();
              return;
            }
            const turnId = runtime.turnId;
            bump();
            if (turnId) resumeTurn(turnId);
          }}
        />
      )}

      {/* Bottom toolbar */}
      <ChatToolbar
        activeSessionId={activeSessionId}
        externalMode={externalMode}
        mode={mode}
        setMode={sessionMode.setMode}
        allowModeSwitch={fixedMode === undefined}
        executionMode={policyMode.executionMode}
        setExecutionMode={policyMode.setExecutionMode}
        executionModePending={policyMode.isPending}
        modelProfiles={profiles}
        activeModelProfileId={activeProfileId}
        activeModelName={activeModelName}
        pickModel={pickModel}
        input={input}
        setInput={setInput}
        streaming={streaming || !!interaction}
        onSend={send}
        onCancel={cancel}
        attachments={attachments}
        setAttachments={setAttachments}
        pendingSubmissions={pending.items}
        activeTurnId={activeRuntime?.turnId ?? null}
        onUpdatePendingSubmission={updateQueuedSubmission}
        onWithdrawPendingSubmission={withdrawQueuedSubmission}
        onRetryPendingSubmission={retryQueuedSubmission}
        onInterruptForSubmission={interruptForQueuedSubmission}
        questionIndexes={questionIndexes}
        onRemoveQuestion={onRemoveQuestion}
        onClearQuestions={onClearQuestions}
        productObjectReferences={productObjectReferences}
        onRemoveProductObjectReference={onRemoveProductObjectReference}
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
            ? sessionList.pendingDelete.error
              ?? (sessionList.pendingDelete.impact
                ? `确定删除「${sessionList.pendingDelete.title}」？\n\n${sessionList.pendingDelete.impact.disclosures.join('\n')}`
                : '正在读取待发送输入、附件、消息与外部调用影响……')
            : ''
        }
        confirmText="删除"
        loading={sessionList.deletingChat}
        confirmDisabled={!sessionList.pendingDelete?.impact || !!sessionList.pendingDelete?.error}
        onConfirm={() => { void sessionList.confirmRemoveChat(); }}
        onCancel={() => { if (!sessionList.deletingChat) sessionList.setPendingDelete(null); }}
      />
    </aside>
  );
}
