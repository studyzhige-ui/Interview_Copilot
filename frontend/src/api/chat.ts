import { apiClient, authedFetch } from './client';
import type {
  ChatSessionCreateResp,
  ChatSessionListItem,
  ChatTranscriptResp,
  Source,
} from '@/types/api';

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
  onBudget?: (info: BudgetInfo, step: number) => void;
  /** Terminal in-stream error (AGT-5) — render into the transcript, don't throw. */
  onStreamError?: (message: string) => void;
}

/** Execution strategy for the turn — picks L1 chat vs L2 ReAct agent on
 *  the server side. The frontend's AGENT pill MUST set ``mode='agent'``
 *  to actually activate the tool registry (search_jobs, web_search,
 *  read_url, search_knowledge, read_resume, read_interview_history,
 *  read_file, write_file, recall_memory, save_memory). Without it the
 *  AGENT pill is decorative and the LLM never sees a single tool. */
type ChatMode = 'chat' | 'agent';

export interface StreamChatOptions {
  signal?: AbortSignal;
  /** Defaults to the direct chat strategy. */
  mode?: ChatMode;
  /** Subscribe to an already-running turn instead of creating one. */
  turnId?: string;
  onTurnCreated?: (turnId: string) => void;
}

function dispatchHarnessEvent(evt: HarnessEvent, handlers: StreamChatHandlers): boolean {
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
    case 'budget': handlers.onBudget?.(data as unknown as BudgetInfo, step); break;
    case 'error': handlers.onStreamError?.(String(data.error ?? 'stream error')); break;
    case 'done': return true;
    default:
      // eslint-disable-next-line no-console
      console.debug('[sse] unknown event type', evt.type, data);
  }
  return false;
}

async function readTurnEvents(
  url: string,
  cursor: { value: string },
  handlers: StreamChatHandlers,
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
          if (dispatchHarnessEvent(JSON.parse(payload) as HarnessEvent, handlers)) return true;
        } catch { /* malformed forward-compatible event */ }
      }
    }
  } catch (error) {
    if (timedOut && !signal?.aborted) throw new Error('连接超时：服务端 60s 无数据响应');
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
): Promise<void> {
  const baseURL = (apiClient.defaults.baseURL ?? '').replace(/\/+$/, '');
  let turnId = opts.turnId;
  if (!turnId) {
    const response = await apiClient.post(
      `/chat/${encodeURIComponent(sessionId)}/turns`,
      { message, mode: opts.mode ?? 'chat' },
      { signal: opts.signal },
    );
    turnId = String(response.data.turn_id);
    opts.onTurnCreated?.(turnId);
  }
  const url = `${baseURL}/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/events`;
  const cursor = { value: '0-0' };
  for (let attempt = 0; attempt < 6; attempt += 1) {
    try {
      if (await readTurnEvents(url, cursor, handlers, opts.signal)) return;
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
}

export async function cancelChatTurn(sessionId: string, turnId: string): Promise<void> {
  await apiClient.post(
    `/chat/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/cancel`,
  );
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


// ── Global-memory toggle (per-session override + per-user default) ───────
// The per-session value lives in the ``conversations.global_memory_enabled``
// column (see backend recall_policy). The GET endpoint resolves the effective
// value: per-session override → user-level default → False, so the switch UI
// never lies about what the next turn will inject.
//
export async function getSessionGlobalMemory(
  sessionId: string,
  opts: { signal?: AbortSignal } = {},
): Promise<boolean> {
  const res = await apiClient.get(
    `/chat/sessions/${encodeURIComponent(sessionId)}/global-memory`,
    { signal: opts.signal },
  );
  return Boolean(res.data?.enabled);
}

export async function setSessionGlobalMemory(
  sessionId: string,
  enabled: boolean,
): Promise<void> {
  await apiClient.post(
    `/chat/sessions/${encodeURIComponent(sessionId)}/global-memory`,
    { enabled },
  );
}
