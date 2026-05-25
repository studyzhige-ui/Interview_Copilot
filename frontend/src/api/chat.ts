import { apiClient } from './client';
import { tokenStore } from '@/lib/token';
import type {
  ChatSessionCreateResp,
  ChatSessionListItem,
  ChatMessageItem,
  ChatTranscriptResp,
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
 * Cancellation: pass an AbortController.signal in ``opts.signal`` —
 * the active fetch is aborted, the server-side generator yields its
 * cleanup hook, and the promise rejects with the signal's reason.
 */

/** Mirrors HarnessEventType in backend/app/agent_runtime/harness_events.py. */
export type HarnessEventType =
  | 'status'
  | 'text_delta'
  | 'text'
  | 'tool_start'
  | 'tool_done'
  | 'budget'
  | 'error'
  | 'done';

export interface HarnessEvent {
  type: HarnessEventType;
  data: Record<string, unknown>;
  step: number;
  elapsed_ms: number;
}

export interface ToolStartInfo {
  tool: string;
  args_summary: string;
  step: number;
  elapsed_ms: number;
}

export interface ToolDoneInfo {
  tool: string;
  result_summary: string;
  step: number;
  elapsed_ms: number;
  tool_latency_ms: number;
  is_error: boolean;
}

/**
 * Agent-mode budget snapshot — emitted exactly once per turn by
 * AgentReActStrategy when the run completes (success or budget-stop).
 * Mirrors ``AgentBudget.to_dict()`` + the ``run_id`` injection in
 * backend/app/conversation/agent_strategy.py:228-229.
 *
 * All fields are always present on the wire — the backend never omits
 * one, so callers may treat them as required (the wire→type cast in
 * ``streamChatSSE`` trusts this).
 */
export interface BudgetInfo {
  /** Agent run id, surfaced so the UI can deep-link to the
   *  /agent/runs trace viewer (developer-only — no user UI yet). */
  run_id: string;
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
   *  ``elapsed_s`` is seconds (per AgentBudget.to_dict). */
  elapsed_s: number;
}

export interface StreamChatHandlers {
  /** Transient "正在生成…" pings. Safe to ignore — UI sugar only. */
  onStatus?: (message: string) => void;
  /** Incremental token. Append to your in-flight assistant buffer. */
  onTextDelta?: (delta: string, step: number) => void;
  /** Agent-mode step boundary: the LLM's text response for this step
   *  is finalized. L1 chat NEVER emits this (delta-only contract).
   *  Treat it as "flush the partial buffer into a finalized text block". */
  onText?: (content: string, step: number) => void;
  onToolStart?: (info: ToolStartInfo) => void;
  onToolDone?: (info: ToolDoneInfo) => void;
  onBudget?: (info: BudgetInfo, step: number) => void;
}

export async function streamChatSSE(
  sessionId: string,
  message: string,
  handlers: StreamChatHandlers,
  opts: { signal?: AbortSignal } = {},
): Promise<void> {
  const token = tokenStore.getAccess() ?? '';
  const baseURL = (apiClient.defaults.baseURL ?? '').replace(/\/+$/, '');
  const url = `${baseURL}/chat/sse/${encodeURIComponent(sessionId)}`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ message }),
    signal: opts.signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = `HTTP ${resp.status}`;
    try {
      const j = await resp.json();
      if (j?.detail) detail = String(j.detail);
    } catch { /* not json — keep status */ }
    throw new Error(detail);
  }

  // SSE frame parser. Lines arrive as ``data: <json>\n`` and frames are
  // delimited by a blank line (``\n\n``). The decoder may split a frame
  // across chunks, so we buffer.
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        // A frame can be multiple ``data:`` lines; concatenate the
        // payloads per the SSE spec. Comment lines (starting ``:``)
        // are heartbeats — skip.
        const payload = frame
          .split('\n')
          .filter((l) => l.startsWith('data:'))
          .map((l) => l.slice(5).trimStart())
          .join('\n');
        if (!payload) continue;
        let evt: HarnessEvent;
        try { evt = JSON.parse(payload) as HarnessEvent; }
        catch { continue; }
        if (!evt || typeof evt.type !== 'string') continue;
        const data = (evt.data ?? {}) as Record<string, unknown>;
        const step = typeof evt.step === 'number' ? evt.step : 0;
        const elapsed = typeof evt.elapsed_ms === 'number' ? evt.elapsed_ms : 0;
        switch (evt.type) {
          case 'status':
            handlers.onStatus?.(String(data.message ?? ''));
            break;
          case 'text_delta':
            handlers.onTextDelta?.(String(data.delta ?? ''), step);
            break;
          case 'text':
            handlers.onText?.(String(data.content ?? ''), step);
            break;
          case 'tool_start':
            handlers.onToolStart?.({
              tool: String(data.tool ?? ''),
              args_summary: String(data.args_summary ?? ''),
              step, elapsed_ms: elapsed,
            });
            break;
          case 'tool_done':
            handlers.onToolDone?.({
              tool: String(data.tool ?? ''),
              result_summary: String(data.result_summary ?? ''),
              tool_latency_ms: Number(data.tool_latency_ms ?? 0),
              is_error: Boolean(data.is_error),
              step, elapsed_ms: elapsed,
            });
            break;
          case 'budget':
            // Wire→type cast: the backend's AgentBudget.to_dict() always
            // emits every BudgetInfo field, so we trust the shape. TS
            // requires the ``unknown`` hop because BudgetInfo's required
            // fields don't structurally overlap with the generic
            // ``Record<string, unknown>`` form of the parsed JSON.
            handlers.onBudget?.(data as unknown as BudgetInfo, step);
            break;
          case 'error':
            // Throw so the caller's .catch() handles it — also lets the
            // ``finally`` release the reader. The server may emit a
            // trailing ``done`` after the error per streaming.py's
            // fallback path; we never reach it because the throw
            // short-circuits the loop, which is the right behaviour
            // (an errored stream is finished from our POV).
            throw new Error(String(data.error ?? 'stream error'));
          case 'done':
            return;
          default:
            // Forward-compat: unknown event types are silently skipped
            // rather than throwing — lets the backend add new event
            // types without lockstep frontend deploys. We log under
            // ``debug`` so a dev with the console open spots a wire
            // drift without a debugger.
            // eslint-disable-next-line no-console
            console.debug('[sse] unknown event type', evt.type, data);
            break;
        }
      }
    }
  } finally {
    try { reader.releaseLock(); } catch { /* ignore */ }
  }
}

export async function createChatSession(payload: {
  session_type: 'general' | 'debrief' | 'mock_interview';
  interview_id?: string;
  title?: string;
}): Promise<ChatSessionCreateResp> {
  const res = await apiClient.post('/chat/sessions', payload);
  return res.data;
}

export async function listChatSessions(
  q: { offset?: number; limit?: number; session_type?: string; interview_id?: string } = {},
): Promise<ChatSessionListItem[]> {
  const res = await apiClient.get('/chat/sessions', {
    params: { offset: 0, limit: 50, ...q },
  });
  return res.data;
}

export async function getChatHistory(
  sessionId: string,
  offset = 0,
  limit = 100,
): Promise<ChatMessageItem[]> {
  const res = await apiClient.get('/chat/history', {
    params: { session_id: sessionId, offset, limit },
  });
  return res.data;
}

/**
 * Block-aware history loader — preferred over ``getChatHistory`` for any
 * UI that needs to replay an L2 agent turn (tool-use / tool-result
 * cards). Returns the full transcript (no pagination) plus session meta.
 *
 * The backend ALWAYS attaches ``blocks[]`` to every message — for
 * legacy rows with no ``content_blocks_json`` it synthesises a single
 * ``text`` block from ``content`` at read time, so the renderer can
 * uniformly branch on ``blocks`` without a flat-string fallback.
 */
export async function getChatTranscript(sessionId: string): Promise<ChatTranscriptResp> {
  const res = await apiClient.get('/chat/transcript', {
    params: { session_id: sessionId },
  });
  return res.data;
}

export async function renameChatSession(sessionId: string, title: string): Promise<void> {
  // Backend now prefers JSON body; query param kept as fallback for compat.
  await apiClient.patch(`/chat/sessions/${encodeURIComponent(sessionId)}/title`, { title });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`);
}


// ── Global-memory toggle (per-session override + per-user default) ───────
// The per-session value lives inside ``chat_sessions.session_state`` JSON
// under the key ``global_memory_enabled`` (legacy key
// ``memory_recall_enabled`` is read for back-compat — see backend
// recall_policy). The GET endpoint resolves the effective value:
// per-session override → user-level default → False, so the switch UI
// never lies about what the next turn will inject.
//
// Note: the endpoint path is still ``/memory-recall`` for back-compat
// (renaming a public URL is more expensive than the function alias).

export async function getSessionGlobalMemory(sessionId: string): Promise<boolean> {
  const res = await apiClient.get(
    `/chat/sessions/${encodeURIComponent(sessionId)}/memory-recall`,
  );
  return Boolean(res.data?.enabled);
}

export async function setSessionGlobalMemory(
  sessionId: string,
  enabled: boolean,
): Promise<void> {
  await apiClient.post(
    `/chat/sessions/${encodeURIComponent(sessionId)}/memory-recall`,
    { enabled },
  );
}
