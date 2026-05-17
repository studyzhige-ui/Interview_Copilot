import { apiClient } from './client';
import { tokenStore } from '@/lib/token';
import type {
  ChatSessionCreateResp,
  ChatSessionListItem,
  ChatMessageItem,
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
 * Wire shape: server emits ``data: { type, content }\n\n`` lines, where
 * type ∈ {"status", "chunk", "done"}. We dispatch to the callbacks
 * accordingly and resolve / reject the returned promise once the
 * server sends ``{type:"done"}`` or the fetch errors.
 *
 * Cancellation: pass an AbortController.signal in ``opts.signal`` —
 * the active fetch is aborted, the server-side generator yields its
 * cleanup hook, and the promise rejects with the signal's reason.
 */
export interface StreamChatHandlers {
  onChunk: (delta: string) => void;
  onStatus?: (status: string) => void;
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
        let evt: { type?: string; content?: string };
        try { evt = JSON.parse(payload); }
        catch { continue; }
        if (evt.type === 'chunk') {
          handlers.onChunk(evt.content ?? '');
        } else if (evt.type === 'status') {
          handlers.onStatus?.(evt.content ?? '');
        } else if (evt.type === 'done') {
          return;
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

export async function renameChatSession(sessionId: string, title: string): Promise<void> {
  // Backend now prefers JSON body; query param kept as fallback for compat.
  await apiClient.patch(`/chat/sessions/${encodeURIComponent(sessionId)}/title`, { title });
}

export async function deleteChatSession(sessionId: string): Promise<void> {
  await apiClient.delete(`/chat/sessions/${encodeURIComponent(sessionId)}`);
}


// ── Memory recall toggle (per-session + per-user) ─────────────────────────
// The per-session value is stored inside chat_sessions.session_state JSON;
// reading via this endpoint also resolves the effective fallback from
// the user-level default, so the switch UI never lies about what the
// agent will actually do on the next turn.

export async function getSessionMemoryRecall(sessionId: string): Promise<boolean> {
  const res = await apiClient.get(
    `/chat/sessions/${encodeURIComponent(sessionId)}/memory-recall`,
  );
  return Boolean(res.data?.enabled);
}

export async function setSessionMemoryRecall(
  sessionId: string,
  enabled: boolean,
): Promise<void> {
  await apiClient.post(
    `/chat/sessions/${encodeURIComponent(sessionId)}/memory-recall`,
    { enabled },
  );
}
