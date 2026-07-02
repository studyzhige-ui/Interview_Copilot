import { useCallback } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import { streamChatSSE } from '@/api/chat';
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
  const sendMessage = useCallback((payload: string) => {
    if (!activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.streaming) return;

    r.messages.push({ role: 'user', content: payload });
    r.partial = '';
    r.inflightBlocks = [];
    r.inflightSources = [];
    r.status = '';
    r.hidePartialBar = false;
    r.streaming = true;
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

    const finalize = (errMsg?: string) => {
      const rt = getRuntime(sid);
      flushPartial(rt);
      if (rt.inflightBlocks.length > 0) {
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
      bump();
    };

    streamChatSSE(sid, payload, {
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
      onToolStart: ({ tool, tool_call_id, args_summary }) => {
        const rt = getRuntime(sid);
        // Flush any text-before-tool so it lands BEFORE the tool card.
        flushPartial(rt);
        // ``tool_call_id`` carries the real LLM-assigned id (post
        // P1-C wire-format upgrade). Writing it onto the inflight
        // block aligns the live-stream shape with the persisted
        // ``/chat/transcript`` shape (which already carried
        // ``tc.id``) — pre/post-reload are now byte-identical.
        //
        // The BlockChain renderer still pairs ``tool_use`` /
        // ``tool_result`` blocks by ADJACENCY today (use[i] →
        // result[i+1]); the wire id is groundwork for switching to
        // id-keyed pairing once an agent dispatches tools in
        // parallel and adjacency becomes unsafe. Empty string from a
        // pre-P1-C backend renders the same as it did then.
        const block: ToolUseBlock = {
          type: 'tool_use',
          id: tool_call_id,
          name: tool,
          // ``args_summary`` is a flat string for display; we surface
          // it under an ``_args_summary`` key so the JSON-inspector
          // view still renders nicely. The persisted shape has full
          // ``input`` (parsed args); during live streaming we don't
          // have the parsed dict yet.
          input: args_summary ? { _args_summary: args_summary } : {},
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
    }, {
      signal: ac.signal,
      // The mode pill (CHAT vs AGENT) selects the server-side strategy.
      // Without this plumbing the AGENT button is purely decorative and
      // the full tool registry never reaches the LLM — see the SSE
      // endpoint's dispatch on ``request.mode``.
      mode: mode === 'AGENT' ? 'agent' : 'chat',
    })
      .then(() => finalize())
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') { finalize(); return; }
        finalize(extractErr(err, '连接失败'));
        toast.error(extractErr(err, '发送失败'));
      });
  }, [activeSessionId, getRuntime, bump, mode]);

  /**
   * Abort the in-flight stream for the active session. Fires the
   * AbortController that ``sendMessage()`` registered on the runtime; the
   * SSE reader's ``fetch`` rejects with AbortError, the promise's
   * ``.catch`` falls into the abort branch, and ``finalize()`` runs
   * normally — so anything streamed so far becomes the assistant
   * message and the panel is ready for the next turn.
   *
   * No-op when no session is selected or no stream is in flight.
   */
  const cancel = useCallback(() => {
    if (!activeSessionId) return;
    const rt = getRuntime(activeSessionId);
    rt.abort?.abort();
  }, [activeSessionId, getRuntime]);

  return { sendMessage, cancel };
}
