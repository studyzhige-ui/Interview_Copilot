import { apiClient, authedFetch } from './client';
import type {
  ChatSessionCreateResp,
  ChatSessionExecutionMode,
  ChatSessionListItem,
  ChatTurnAdmissionResp,
  ChatTranscriptResp,
  PendingSubmissionItem,
  ProductObjectReference,
  AttachmentDraft,
  AttachmentRetryResp,
  AttachmentSource,
  ConversationAttachmentRemovalResp,
  AgentTask,
  AgentToolCallAudit,
  AgentInteraction,
  ResolveAgentInteractionResp,
  Source,
} from '@/types/api';
import { emitMockClientActionNotice } from './clientActions';
import type { MockClientActionName } from '@/types/clientAction';

/**
 * Stream a chat turn over Server-Sent Events.
 *
 * Why SSE instead of the legacy WebSocket: every major chat API
 * (OpenAI / Anthropic / Gemini) uses SSE for one-way text streaming.
 * SSE rides standard HTTP — gets free proxy / CDN / nginx friendliness,
 * standard JWT bearer auth (no subprotocol-token hack), and works
 * through corporate firewalls that often block WebSocket. WebSocket
 * is only useful for bidirectional realtime (voice). Mock interview
 * keeps the WS endpoint server-side as a forward hook for real-time
 * voice but its text-only flow goes through this same helper.
 *
 * Wire shape (Stage-G unified — see backend/app/agent_runtime/
 * harness_events.py for the source of truth):
 *
 *     data: {"type": "<HarnessEventType>", "data": {...},
 *            "step": N, "elapsed_ms": M}\n\n
 *
 * Event types we expect:
 *   - status      data.message   transient progress hint
 *   - sources     data.sources   L1 RAG [K#] citation sources (once, before
 *                                generation; absent for direct chat / agent)
 *   - text_delta  data.delta     incremental token (THE new "chunk")
 *   - text        data.content   step-final consolidated text (agent only;
 *                                L1 chat is delta-only and never emits this)
 *   - tool_start  data.{tool, args_summary}                (agent only)
 *   - tool_done   data.{tool, result_summary,
 *                       tool_latency_ms, is_error}         (agent only)
 *   - budget      data.{run_id, prompt_tokens, ...}        (agent only — once)
 *   - error       data.error     terminal: promise rejects
 *   - done                       terminal: promise resolves
 *
 * Aborting the signal detaches this subscription. The chat toolbar first
 * requests server-side turn cancellation, then aborts this stream.
 */

/** Mirrors HarnessEventType in backend/app/agent_runtime/harness_events.py. */
type HarnessEventType =
  | 'status'
  | 'sources'
  | 'text_delta'
  | 'text'
  | 'tool_start'
  | 'tool_done'
  | 'interaction'
  | 'budget'
  | 'error'
  | 'done';

interface HarnessEvent {
  type: HarnessEventType;
  data: Record<string, unknown>;
  step: number;
  elapsed_ms: number;
}

interface ToolStartInfo {
  tool: string;
  /** LLM-assigned tool call id (e.g. ``call_AbC123``). Mirrors the
   *  matching ``tool_done.tool_call_id`` so the renderer can pair
   *  live-stream tool_use/tool_result blocks by id rather than FIFO
   *  order — robust to parallel tool calls and makes the live shape
   *  match what ``/chat/transcript`` persists. Empty string from
   *  matching ``tool_done`` event. */
  tool_call_id: string;
  /** Full parsed input dict (AGT-5, live == replay) — matches the
   *  persisted tool_use block. */
  input: Record<string, unknown>;
  step: number;
  elapsed_ms: number;
}

interface ToolDoneInfo {
  tool: string;
  /** Mirrors ``tool_start.tool_call_id`` — use for id-based pairing
   *  of live tool_use/tool_result blocks. */
  tool_call_id: string;
  result_summary: string;
  /** Full LLM-visible result text (post Stage-G+ wire format).
   *  Populated live by the agent strategy so the expanded tool card
   *  renders without a session refresh. Empty string when the
   *  upstream emitter omits it (e.g. a very old backend); the
   *  renderer falls back to "(刷新会话以加载完整输出)" then. */
  result_content: string;
  step: number;
  elapsed_ms: number;
  tool_latency_ms: number;
  is_error: boolean;
}

/**
 * Agent-mode usage snapshot — emitted exactly once per turn by
 * AgentLoopStrategy when the run completes. The legacy event name is
 * ``budget`` for wire compatibility, but none of these observations is a
 * task-termination limit. Mirrors ``AgentRunState.to_dict()`` in
 * backend/app/agent_runtime/react_agent.py.
 *
 * All fields are always present on the wire — the backend never omits
 * one, so callers may treat them as required (the wire→type cast in
 * ``streamChatTurn`` trusts this).
 */
interface BudgetInfo {
  /** ReAct steps consumed this turn. */
  steps: number;
  /** Total tool calls dispatched this turn. */
  tool_calls: number;
  /** Sum of prompt tokens across all step LLM calls. */
  prompt_tokens: number;
  /** Sum of completion tokens across all step LLM calls. */
  completion_tokens: number;
  /** Wall-clock SECONDS spent in this turn. NB: the outer
   *  ``HarnessEvent.elapsed_ms`` is milliseconds; this nested
   *  ``elapsed_s`` is seconds (per AgentRunState.to_dict). */
  elapsed_s: number;
}

export interface StreamChatHandlers {
  /** Transient "正在生成…" pings. Safe to ignore — UI sugar only. */
  onStatus?: (message: string) => void;
  /** L1 RAG citation sources for the turn — fired once before generation.
   *  Store them on the in-flight assistant message so [K#] resolves to a
   *  source card. Never fires for direct chat / agent turns. */
  onSources?: (sources: Source[]) => void;
  /** Incremental token. Append to your in-flight assistant buffer. */
  onTextDelta?: (delta: string, step: number) => void;
  /** Agent-mode step boundary: the LLM's text response for this step
   *  is finalized. L1 chat NEVER emits this (delta-only contract).
   *  Treat it as "flush the partial buffer into a finalized text block". */
  onText?: (content: string, step: number) => void;
  onToolStart?: (info: ToolStartInfo) => void;
  onToolDone?: (info: ToolDoneInfo) => void;
  onInteraction?: (interaction: AgentInteraction) => void;
  onBudget?: (info: BudgetInfo, step: number) => void;
  /** Terminal in-stream error (AGT-5) — render into the transcript, don't throw. */
  onStreamError?: (message: string) => void;
}

/** Execution strategy for the turn — picks direct chat vs the shared
 *  tool-using Agent runtime on the server. */
type ChatMode = 'chat' | 'agent';

export interface ChatSubmissionIdentity {
  submissionId: string;
  version: number;
  sourceClientId: string;
}

const SOURCE_CLIENT_ID_KEY = 'chat-source-client-instance-id-v2';

function randomId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `${prefix}_${uuid}`;
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

export function getSourceClientId(): string {
  try {
    // sessionStorage is scoped to one tab/client instance. localStorage made
    // every tab share an identity, which could broadcast a Client Action to
    // the wrong UI consumer.
    const existing = sessionStorage.getItem(SOURCE_CLIENT_ID_KEY);
    if (existing) return existing;
    const created = randomId('client');
    sessionStorage.setItem(SOURCE_CLIENT_ID_KEY, created);
    return created;
  } catch {
    return randomId('client');
  }
}

/** Create once for a real Send action, then reuse across transport retries. */
export function createChatSubmissionIdentity(): ChatSubmissionIdentity {
  return {
    submissionId: randomId('submission'),
    version: 1,
    sourceClientId: getSourceClientId(),
  };
}

export interface StreamChatOptions {
  signal?: AbortSignal;
  /** Defaults to the direct chat strategy. */
  mode?: ChatMode;
  /** Legacy wire hint only. The server rereads the Conversation owner and
   *  freezes the authoritative value on PendingSubmission/Turn admission. */
  executionMode?: 'standard' | 'auto';
  /** Explicit 1-based QA-card references for this debrief turn. */
  questionIndexes?: number[];
  /** Durable Composer draft ids revalidated and frozen at admission. */
  attachments?: string[];
  /** Explicit product identities; copied labels/business fields are omitted. */
  objectReferences?: ProductObjectReference[];
  /** Subscribe to an already-running turn instead of creating one. */
  turnId?: string;
  /** Stable identity created once by the Composer's Send action. */
  submission?: ChatSubmissionIdentity;
  onAdmission?: (admission: ChatTurnAdmissionResp) => void;
  onTurnCreated?: (turnId: string) => void;
}

function retryableAdmissionError(error: unknown): boolean {
  const status = (error as { response?: { status?: number } })?.response?.status;
  return status === undefined || status === 429 || status >= 500;
}

function retryDelay(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  return new Promise<void>((resolve, reject) => {
    const timerId = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(timerId);
      reject(new DOMException('Aborted', 'AbortError'));
    }, { once: true });
  });
}

async function admitChatTurn(
  sessionId: string,
  message: string,
  opts: StreamChatOptions,
): Promise<ChatTurnAdmissionResp> {
  const identity = opts.submission ?? createChatSubmissionIdentity();
  const body = {
    submission_id: identity.submissionId,
    version: identity.version,
    message,
    mode: opts.mode ?? 'chat',
    execution_mode: opts.executionMode ?? 'standard',
    question_indexes: opts.questionIndexes ?? [],
    attachments: (opts.attachments ?? []).map((draft_id) => ({ draft_id })),
    object_references: (opts.objectReferences ?? []).map(({ kind, object_id }) => ({
      kind,
      object_id,
    })),
    source_client_id: identity.sourceClientId,
  };
  for (let attempt = 0; ; attempt += 1) {
    try {
      const response = await apiClient.post(
        `/chat/${encodeURIComponent(sessionId)}/turns`,
        body,
        { signal: opts.signal },
      );
      return response.data as ChatTurnAdmissionResp;
    } catch (error) {
      if (opts.signal?.aborted || attempt >= 2 || !retryableAdmissionError(error)) throw error;
      await retryDelay(200 * 2 ** attempt, opts.signal);
    }
  }
}

export async function createAttachmentDraft(
  sessionId: string,
  fileAssetId: string,
  draftId?: string,
): Promise<AttachmentDraft> {
  const response = await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/attachment-drafts`,
    { file_asset_id: fileAssetId, ...(draftId ? { draft_id: draftId } : {}) },
  );
  return response.data as AttachmentDraft;
}

export async function removeAttachmentDraft(
  sessionId: string,
  draftId: string,
): Promise<AttachmentDraft> {
  const response = await apiClient.delete(
    `/chat/${encodeURIComponent(sessionId)}/attachment-drafts/${encodeURIComponent(draftId)}`,
  );
  return response.data as AttachmentDraft;
}

export async function getAttachmentDraft(
  sessionId: string,
  draftId: string,
  signal?: AbortSignal,
): Promise<AttachmentDraft> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(sessionId)}/attachment-drafts/${encodeURIComponent(draftId)}`,
    { signal },
  );
  return response.data as AttachmentDraft;
}

export async function waitForAttachmentDraft(
  sessionId: string,
  draftId: string,
  opts: { signal?: AbortSignal; pollMs?: number } = {},
): Promise<AttachmentDraft> {
  const pollMs = Math.max(250, opts.pollMs ?? 800);
  for (;;) {
    const draft = await getAttachmentDraft(sessionId, draftId, opts.signal);
    if (draft.status === 'ready') return draft;
    if (draft.status === 'failed' || draft.status === 'removed') return draft;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, pollMs);
      opts.signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    });
  }
}

/** List admitted Conversation attachments, or one retained submission's drafts. */
export async function listAttachmentSources(
  sessionId: string,
  opts: { submissionId?: string; turnId?: string; signal?: AbortSignal } = {},
): Promise<AttachmentSource[]> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(sessionId)}/attachment-sources`,
    {
      params: {
        ...(opts.submissionId ? { submission_id: opts.submissionId } : {}),
        ...(opts.turnId ? { turn_id: opts.turnId } : {}),
      },
      signal: opts.signal,
    },
  );
  return response.data as AttachmentSource[];
}

/** Retry the same failed parsing projection without changing source identity. */
export async function retryAttachmentSource(
  sessionId: string,
  sourceId: string,
): Promise<AttachmentRetryResp> {
  const response = await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/attachment-sources/${encodeURIComponent(sourceId)}/retry`,
  );
  return response.data as AttachmentRetryResp;
}

/** Remove one failed claimed Conversation source and let the server decide
 *  whether the attachment-waiting Turn can resume. */
export async function removeFailedConversationAttachment(
  sessionId: string,
  attachmentRefId: string,
): Promise<ConversationAttachmentRemovalResp> {
  const response = await apiClient.delete(
    `/chat/${encodeURIComponent(sessionId)}/attachment-sources/${encodeURIComponent(attachmentRefId)}`,
  );
  return response.data as ConversationAttachmentRemovalResp;
}

/** Explicitly share one Conversation attachment with this InterviewRecord only. */
export async function promoteAttachmentToDebrief(
  sessionId: string,
  attachmentRefId: string,
): Promise<AttachmentSource> {
  const response = await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/attachment-sources/${encodeURIComponent(attachmentRefId)}/debrief`,
  );
  return (response.data as { source: AttachmentSource }).source;
}

export async function listDebriefSources(
  interviewRecordId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<AttachmentSource[]> {
  const response = await apiClient.get(
    `/interviews/${encodeURIComponent(interviewRecordId)}/debrief-sources`,
    { signal: opts.signal },
  );
  return response.data as AttachmentSource[];
}

export async function removeDebriefSource(
  interviewRecordId: string,
  sourceRefId: string,
): Promise<void> {
  await apiClient.delete(
    `/interviews/${encodeURIComponent(interviewRecordId)}/debrief-sources/${encodeURIComponent(sourceRefId)}`,
  );
}

function dispatchHarnessEvent(
  evt: HarnessEvent,
  handlers: StreamChatHandlers,
  sessionId: string,
): boolean {
  if (!evt || typeof evt.type !== 'string') return false;
  const data = (evt.data ?? {}) as Record<string, unknown>;
  const step = typeof evt.step === 'number' ? evt.step : 0;
  const elapsed = typeof evt.elapsed_ms === 'number' ? evt.elapsed_ms : 0;
  switch (evt.type) {
    case 'status': handlers.onStatus?.(String(data.message ?? '')); break;
    case 'sources':
      handlers.onSources?.(Array.isArray(data.sources) ? data.sources as Source[] : []);
      break;
    case 'text_delta': handlers.onTextDelta?.(String(data.delta ?? ''), step); break;
    case 'text': handlers.onText?.(String(data.content ?? ''), step); break;
    case 'tool_start':
      handlers.onToolStart?.({
        tool: String(data.tool ?? ''),
        tool_call_id: String(data.tool_call_id ?? ''),
        input: data.input && typeof data.input === 'object'
          ? data.input as Record<string, unknown>
          : {},
        step,
        elapsed_ms: elapsed,
      });
      break;
    case 'tool_done':
      handlers.onToolDone?.({
        tool: String(data.tool ?? ''),
        tool_call_id: String(data.tool_call_id ?? ''),
        result_summary: String(data.result_summary ?? ''),
        result_content: String(data.result_content ?? ''),
        tool_latency_ms: Number(data.tool_latency_ms ?? 0),
        is_error: Boolean(data.is_error),
        step,
        elapsed_ms: elapsed,
      });
      break;
    case 'interaction': {
      const interaction = data.interaction;
      if (interaction && typeof interaction === 'object') {
        const typed = interaction as AgentInteraction;
        handlers.onInteraction?.(typed);
        const request = typed.request as Record<string, unknown>;
        if (
          typed.kind === 'client_readiness'
          && typed.tool_call_id
          && request.protocol === 'mock_handoff.v1'
          && typeof request.action_id === 'string'
          && typeof request.action === 'string'
        ) {
          emitMockClientActionNotice({
            sessionId,
            turnId: typed.turn_id,
            interactionId: typed.id,
            version: typed.version,
            actionId: request.action_id,
            action: request.action as MockClientActionName,
          });
        }
      }
      break;
    }
    case 'budget': handlers.onBudget?.(data as unknown as BudgetInfo, step); break;
    case 'error': handlers.onStreamError?.(String(data.error ?? 'stream error')); break;
    case 'done': return true;
    default:
      console.debug('[sse] unknown event type', evt.type, data);
  }
  return false;
}

async function readTurnEvents(
  url: string,
  cursor: { value: string },
  handlers: StreamChatHandlers,
  sessionId: string,
  signal?: AbortSignal,
): Promise<boolean> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const armTimeout = () => {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => { timedOut = true; abort(); }, 60_000);
  };
  armTimeout();
  try {
    const separator = url.includes('?') ? '&' : '?';
    const resp = await authedFetch(
      `${url}${separator}after=${encodeURIComponent(cursor.value)}`,
      { headers: { Accept: 'text/event-stream' }, signal: controller.signal },
    );
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
    reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return false;
      armTimeout();
      buf += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        for (const line of frame.split('\n')) {
          if (line.startsWith('id:')) cursor.value = line.slice(3).trim();
        }
        const payload = frame.split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n');
        if (!payload) continue;
        try {
          if (dispatchHarnessEvent(
            JSON.parse(payload) as HarnessEvent,
            handlers,
            sessionId,
          )) return true;
        } catch { /* malformed forward-compatible event */ }
      }
    }
  } catch (error) {
    if (timedOut && !signal?.aborted) {
      throw new Error('连接超时：服务端 60s 无数据响应', { cause: error });
    }
    throw error;
  } finally {
    if (idleTimer) clearTimeout(idleTimer);
    try { reader?.releaseLock(); } catch { /* already released */ }
    signal?.removeEventListener('abort', abort);
  }
}

export async function streamChatTurn(
  sessionId: string,
  message: string,
  handlers: StreamChatHandlers,
  opts: StreamChatOptions = {},
): Promise<ChatTurnAdmissionResp | null> {
  const baseURL = (apiClient.defaults.baseURL ?? '').replace(/\/+$/, '');
  let turnId = opts.turnId;
  let admission: ChatTurnAdmissionResp | null = null;
  if (!turnId) {
    admission = await admitChatTurn(sessionId, message, opts);
    opts.onAdmission?.(admission);
    if (admission.status !== 'admitted') return admission;
    if (!admission.turn_id) throw new Error('服务端已接收请求，但未返回 turn_id');
    turnId = admission.turn_id;
    opts.onTurnCreated?.(turnId);
  }
  const url = `${baseURL}/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/events`;
  const cursor = { value: '0-0' };
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      if (await readTurnEvents(url, cursor, handlers, sessionId, opts.signal)) return admission;
    } catch (error) {
      if (opts.signal?.aborted || attempt === 5) throw error;
    }
    await new Promise<void>((resolve, reject) => {
      const timerId = setTimeout(resolve, Math.min(250 * 2 ** attempt, 2_000));
      opts.signal?.addEventListener('abort', () => {
        clearTimeout(timerId);
        reject(new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    });
  }
  return admission;
}

export async function listPendingSubmissions(
  sessionId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<PendingSubmissionItem[]> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(sessionId)}/submissions`,
    { signal: opts.signal },
  );
  return response.data as PendingSubmissionItem[];
}

export interface UpdatePendingSubmissionPayload {
  expected_version: number;
  message: string;
  attachments: Array<{ draft_id: string }>;
  question_indexes: number[];
  object_references: ProductObjectReference[];
  mode: 'chat' | 'agent';
  execution_mode: 'standard' | 'auto';
}

/** CAS-edit one server-retained Composer submission without changing its place. */
export async function updatePendingSubmission(
  sessionId: string,
  submissionId: string,
  payload: UpdatePendingSubmissionPayload,
): Promise<PendingSubmissionItem> {
  const response = await apiClient.patch(
    `/chat/${encodeURIComponent(sessionId)}/submissions/${encodeURIComponent(submissionId)}`,
    payload,
  );
  return response.data as PendingSubmissionItem;
}

/** Explicitly retry a retained submission, using its server version as a CAS token. */
export async function retryPendingSubmission(
  sessionId: string,
  submissionId: string,
  expectedVersion: number,
): Promise<ChatTurnAdmissionResp> {
  const response = await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/submissions/${encodeURIComponent(submissionId)}/retry`,
    { expected_version: expectedVersion },
  );
  return response.data as ChatTurnAdmissionResp;
}

/** Withdraw one unclaimed submission and let the server reconcile the queue. */
export async function withdrawPendingSubmission(
  sessionId: string,
  submissionId: string,
  expectedVersion: number,
): Promise<void> {
  await apiClient.delete(
    `/chat/${encodeURIComponent(sessionId)}/submissions/${encodeURIComponent(submissionId)}`,
    { params: { expected_version: expectedVersion } },
  );
}

/** Request the one allowed FIFO exception: stop the active turn and send this item. */
export async function interruptChatTurnForSubmission(
  sessionId: string,
  activeTurnId: string,
  submissionId: string,
  expectedVersion: number,
): Promise<void> {
  await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(activeTurnId)}/interrupt`,
    { submission_id: submissionId, expected_version: expectedVersion },
  );
}

export async function cancelChatTurn(sessionId: string, turnId: string): Promise<void> {
  await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/cancel`,
  );
}

export async function resolveAgentInteraction(
  sessionId: string,
  turnId: string,
  interactionId: string,
  payload: {
    expected_version: number;
    status: 'resolved' | 'rejected' | 'cancelled';
    resolution: Record<string, unknown>;
  },
): Promise<ResolveAgentInteractionResp> {
  const response = await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}`
      + `/interactions/${encodeURIComponent(interactionId)}/resolve`,
    payload,
  );
  return response.data as ResolveAgentInteractionResp;
}

/** Read the one optional flat plan for an active or historical Agent Turn. */
export async function getAgentTask(
  sessionId: string,
  turnId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<AgentTask | null> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/agent-task`,
    { signal: opts.signal },
  );
  return response.data as AgentTask | null;
}

/** Load the durable audit layer for the same call id shown live and in History. */
export async function getToolCallAudit(
  sessionId: string,
  turnId: string,
  callId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<AgentToolCallAudit> {
  const response = await apiClient.get(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}`
      + `/tool-calls/${encodeURIComponent(callId)}`,
    { signal: opts.signal },
  );
  return response.data as AgentToolCallAudit;
}

export async function createChatSession(payload: {
  // mock_interview sessions are created by the mock-interview start endpoint,
  // never here — this only opens general / debrief chats.
  type: 'general' | 'debrief';
  /** The interview_record this conversation is about (required for debrief). */
  subject_id?: string;
  title?: string;
}): Promise<ChatSessionCreateResp> {
  const res = await apiClient.post('/chat/sessions', payload);
  return res.data;
}

export async function listChatSessions(
  q: { offset?: number; limit?: number; type?: string; subject_id?: string } = {},
  opts: { signal?: AbortSignal } = {},
): Promise<ChatSessionListItem[]> {
  const res = await apiClient.get('/chat/sessions', {
    params: { offset: 0, limit: 50, ...q },
    signal: opts.signal,
  });
  return res.data;
}

export async function getChatSessionExecutionMode(
  sessionId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<ChatSessionExecutionMode> {
  const res = await apiClient.get(
    `/chat/sessions/${encodeURIComponent(sessionId)}/execution-mode`,
    { signal: opts.signal },
  );
  return res.data as ChatSessionExecutionMode;
}

export async function updateChatSessionExecutionMode(
  sessionId: string,
  executionMode: 'standard' | 'auto',
  expectedVersion: number,
): Promise<ChatSessionExecutionMode> {
  const res = await apiClient.patch(
    `/chat/sessions/${encodeURIComponent(sessionId)}/execution-mode`,
    { execution_mode: executionMode, expected_version: expectedVersion },
  );
  return res.data as ChatSessionExecutionMode;
}

/**
 * Block-aware transcript loader for replaying direct-chat and agent turns.
 * Returns the full transcript (no pagination) plus session metadata.
 *
 * The backend ALWAYS attaches ``blocks[]`` to every message — for
 * legacy rows with no ``content_blocks_json`` it synthesises a single
 * ``text`` block from ``content`` at read time, so the renderer can
 * uniformly branch on ``blocks`` without a flat-string fallback.
 *
 * Pass ``opts.signal`` from a session-switch ``AbortController`` so
 * a stale response from a previous session can't land on the active
 * runtime after the user has navigated away — the
 * ``runtimes.current`` Map is keyed by session_id and a delayed
 * response from session A could overwrite session B's messages
 * during rapid sidebar clicks.
 */
export async function getChatTranscript(
  sessionId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<ChatTranscriptResp> {
  const res = await apiClient.get('/chat/transcript', {
    params: { session_id: sessionId },
    signal: opts.signal,
  });
  return res.data;
}

export async function renameChatSession(sessionId: string, title: string): Promise<void> {
  await apiClient.patch(`/chat/sessions/${encodeURIComponent(sessionId)}/title`, { title });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`);
}
