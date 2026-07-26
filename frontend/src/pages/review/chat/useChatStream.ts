import { useCallback } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { cancelChatTurn, streamChatTurn } from '@/api/chat';
import type { ToolResultBlock, ToolUseBlock } from '@/types/api';
import type { Mode, SessionRuntime } from './types';

/**
 * The SSE send/cancel pair. Operates on the session-runtime cache: the
 * caller owns input/attachment state and passes the composed payload in;
 * this hook owns the streaming lifecycle (status/sources/deltas/tool
 * events → inflight blocks → finalized assistant message).
 */
export function useChatStream({
  activeSessionId,
  getRuntime,
  bump,
  mode,
}: {
  activeSessionId: string | null;
  getRuntime: (id: string) => SessionRuntime;
  bump: () => void;
  mode: Mode;
}) {
  const startStream = useCallback((payload: string | null, existingTurnId?: string) => {
    if (!activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.streaming || (r.turnId && !existingTurnId)) return;

    if (payload !== null) r.messages.push({ role: 'user', content: payload });
    r.partial = '';
    r.inflightBlocks = [];
    r.inflightSources = [];
    r.status = '';
    r.hidePartialBar = false;
    r.streaming = true;
    r.turnId = existingTurnId ?? null;
    bump();

    const ac = new AbortController();
    r.abort = ac;
    const sid = activeSessionId;

    /** Push the current ``partial`` (if any) onto inflightBlocks as a
     *  text block, then reset. Called at step boundaries: when a
     *  ``text`` event marks the assistant text complete for the step,
     *  or when a tool starts (the text-before-tool needs to be a
     *  separate block from the text-after-tool). */
    const flushPartial = (rt: SessionRuntime) => {
      const trimmed = rt.partial.trim();
      if (!trimmed) { rt.partial = ''; return; }
      rt.inflightBlocks.push({ type: 'text', text: rt.partial });
      rt.partial = '';
    };

    const finalize = (errMsg?: string, detached = false) => {
      const rt = getRuntime(sid);
      if (!detached) flushPartial(rt);
      if (!detached && rt.inflightBlocks.length > 0) {
        // Build a flat-content fallback (last text block's body) so any
        // surface that ignores ``blocks`` still has something to show.
        const lastText = [...rt.inflightBlocks].reverse()
          .find((b): b is { type: 'text'; text: string } => b.type === 'text');
        rt.messages.push({
          role: 'assistant',
          content: lastText?.text ?? '',
          blocks: rt.inflightBlocks,
          sources: rt.inflightSources.length ? rt.inflightSources : undefined,
        });
      } else if (errMsg) {
        rt.messages.push({ role: 'system', content: `（连接中断：${errMsg}）` });
      }
      rt.partial = '';
      rt.inflightBlocks = [];
      rt.inflightSources = [];
      rt.status = '';
      rt.streaming = false;
      rt.hidePartialBar = false;
      rt.abort = null;
      if (!detached) rt.turnId = null;
      bump();
    };

    streamChatTurn(sid, payload ?? '', {
      onStatus: (status) => {
        const rt = getRuntime(sid);
        rt.status = status;
        rt.streaming = true;
        bump();
      },
      onSources: (sources) => {
        // Arrives once before the first token (L1 RAG only). Stash on the
        // runtime so the source-card panel + [K#] resolve as the answer
        // streams; finalize() attaches it to the assistant message.
        const rt = getRuntime(sid);
        rt.inflightSources = sources;
        bump();
      },
      onTextDelta: (delta) => {
        const rt = getRuntime(sid);
        rt.partial += delta;
        rt.streaming = true;
        bump();
      },
      // Step-boundary marker (agent only). The accumulated ``partial``
      // (which the server-side ``text_delta`` chain populated) becomes
      // a finalized text block. We prefer ``rt.partial`` over the
      // event's ``content`` since they should be identical — the
      // event is a redundancy check, not a re-render.
      onText: (content) => {
        const rt = getRuntime(sid);
        if (!rt.partial.trim() && content) {
          // Defensive: agent emitted ``text`` without prior deltas
          // (e.g. non-streamed model). Use the event payload directly.
          rt.partial = content;
        }
        flushPartial(rt);
        rt.streaming = true;
        bump();
      },
      onToolStart: ({ tool, tool_call_id, input }) => {
        const rt = getRuntime(sid);
        // Flush any text-before-tool so it lands BEFORE the tool card.
        flushPartial(rt);
        // ``tool_call_id`` carries the real LLM-assigned id (post
        // P1-C wire-format upgrade). Writing it onto the inflight
        // block aligns the live-stream shape with the persisted
        // ``/chat/transcript`` shape (which already carried
        // ``tc.id``) — pre/post-reload are now byte-identical.
        //
        const block: ToolUseBlock = {
          type: 'tool_use',
          id: tool_call_id,
          name: tool,
          // live == replay: the event and persisted block share the
          // same parsed input dictionary.
          input,
        };
        rt.inflightBlocks.push(block);
        rt.status = `🔧 ${tool}`;
        rt.streaming = true;
        bump();
      },
      onToolDone: ({ tool, tool_call_id, result_summary, result_content, is_error, tool_latency_ms }) => {
        const rt = getRuntime(sid);
        const block: ToolResultBlock = {
          type: 'tool_result',
          // Mirrors ``onToolStart.tool_call_id`` — when present,
          // BlockChain pairs use/result by id; falls back to FIFO
          // order on empty id (pre-P1-C backends).
          tool_use_id: tool_call_id,
          is_error,
          latency_ms: tool_latency_ms,
          summary: result_summary,
          // Full content now streams alongside the summary, so the
          // expanded card renders immediately — no more "refresh to
          // load" placeholder. ``result_content`` is already capped
          // by the tool's ``max_result_chars`` so this stays bounded.
          content: result_content,
        };
        rt.inflightBlocks.push(block);
        const icon = is_error ? '✗' : '✓';
        rt.status = `${icon} ${tool}${result_summary ? ` · ${result_summary}` : ''}`;
        rt.streaming = true;
        bump();
      },
      onStreamError: (message) => {
        // Terminal in-stream error (AGT-5): render it as a notice block in
        // the transcript — the graceful-fallback text (if any) follows on
        // the same stream, so what the user sees live now matches what a
        // reload replays from the persisted blocks.
        const rt = getRuntime(sid);
        flushPartial(rt);
        rt.inflightBlocks.push({ type: 'text', text: `⚠️ ${message}` });
        rt.status = '出错了';
        bump();
      },
    }, {
      signal: ac.signal,
      // The mode pill (CHAT vs AGENT) selects the server-side strategy;
      // the server persists it onto conversations.mode (AGT-4), so a
      // fresh device resumes the same mode without localStorage.
      mode: mode === 'AGENT' ? 'agent' : 'chat',
      turnId: existingTurnId,
      onTurnCreated: (turnId) => {
        getRuntime(sid).turnId = turnId;
      },
    })
      .then(() => finalize())
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') {
          finalize(undefined, Boolean(getRuntime(sid).turnId));
          return;
        }
        const detached = Boolean(getRuntime(sid).turnId);
        finalize(detached ? undefined : extractErr(err, '连接失败'), detached);
        toast.error(extractErr(err, '发送失败'));
      });
  }, [activeSessionId, getRuntime, bump, mode]);

  const sendMessage = useCallback(
    (payload: string) => startStream(payload),
    [startStream],
  );

  const resumeTurn = useCallback(
    (turnId: string) => startStream(null, turnId),
    [startStream],
  );

  /**
   * Abort the active server-side turn and close the local subscription.
   */
  const cancel = useCallback(() => {
    if (!activeSessionId) return;
    const rt = getRuntime(activeSessionId);
    const abort = rt.abort;
    if (rt.turnId) {
      const turnId = rt.turnId;
      void cancelChatTurn(activeSessionId, turnId)
        .catch(() => { /* the local abort still takes effect */ })
        .finally(() => {
          getRuntime(activeSessionId).turnId = null;
          abort?.abort();
        });
      return;
    }
    abort?.abort();
  }, [activeSessionId, getRuntime]);

  return { sendMessage, resumeTurn, cancel };
}
