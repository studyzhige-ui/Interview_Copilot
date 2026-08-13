import { useCallback } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  cancelChatTurn,
  createChatSubmissionIdentity,
  streamChatTurn,
} from '@/api/chat';
import type { ChatSubmissionIdentity } from '@/api/chat';
import type {
  ProductObjectReference,
  ToolResultBlock,
  ToolUseBlock,
} from '@/types/api';
import type { Attachment, Mode, SessionRuntime } from './types';

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
  executionMode,
  onQueueChanged,
  onAgentTaskChanged,
  onObjectReferencesConsumed,
}: {
  activeSessionId: string | null;
  getRuntime: (id: string) => SessionRuntime;
  bump: () => void;
  mode: Mode;
  executionMode: 'standard' | 'auto';
  onQueueChanged?: () => void;
  onAgentTaskChanged?: (sessionId: string, turnId: string) => void;
  onObjectReferencesConsumed?: () => void;
}) {
  const startStream = useCallback((
    payload: string | null,
    existingTurnId?: string,
    questionIndexes: number[] = [],
    attachments: Attachment[] = [],
    objectReferences: ProductObjectReference[] = [],
    submission?: ChatSubmissionIdentity,
  ) => {
    if (!activeSessionId) return;
    const r = getRuntime(activeSessionId);
    if (r.streaming || (r.turnId && !existingTurnId)) return;

    let optimisticUserMessage: SessionRuntime['messages'][number] | null = null;
    if (payload !== null) {
      optimisticUserMessage = {
        role: 'user',
        content: payload,
        blocks: [
          ...attachments.map((attachment) => ({
            type: 'attachment_draft' as const,
            draft_id: attachment.draft_id,
            file_asset_id: attachment.file_asset_id,
            title: attachment.filename,
          })),
          ...objectReferences.map((reference) => ({
            type: 'product_object_reference' as const,
            kind: reference.kind,
            object_id: reference.object_id,
            label: reference.label ?? reference.object_id,
          })),
          { type: 'text' as const, text: payload },
        ],
      };
      r.messages.push(optimisticUserMessage);
    }
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
      const waiting = Boolean(rt.interaction);
      if (!detached) flushPartial(rt);
      if (!detached && !waiting && rt.inflightBlocks.length > 0) {
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
      if (!waiting) {
        rt.partial = '';
        rt.inflightBlocks = [];
        rt.inflightSources = [];
      }
      rt.status = '';
      rt.streaming = false;
      rt.hidePartialBar = false;
      rt.abort = null;
      if (!detached && !waiting) rt.turnId = null;
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
        if ((tool === 'task_create' || tool === 'task_update') && rt.turnId) {
          onAgentTaskChanged?.(sid, rt.turnId);
        }
      },
      onInteraction: (interaction) => {
        const rt = getRuntime(sid);
        rt.interaction = interaction;
        rt.status = '等待你的确认';
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
      // Debrief's mode pill selects the strategy; Career ChatPanel passes a
      // fixed AGENT mode. The backend applies the same runtime policy, so an
      // old client cannot silently downgrade a general session to L1 chat.
      mode: mode === 'AGENT' ? 'agent' : 'chat',
      executionMode,
      questionIndexes,
      attachments: attachments.map((attachment) => attachment.draft_id),
      objectReferences,
      turnId: existingTurnId,
      submission,
      onAdmission: () => {
        if (objectReferences.length > 0) onObjectReferencesConsumed?.();
      },
      onTurnCreated: (turnId) => {
        getRuntime(sid).turnId = turnId;
        // Expose the durable identity immediately so the optional AgentTask
        // read projection can start before the first model status event.
        bump();
      },
    })
      .then((admission) => {
        if (admission && admission.status !== 'admitted' && optimisticUserMessage) {
          const runtime = getRuntime(sid);
          const index = runtime.messages.indexOf(optimisticUserMessage);
          if (index >= 0) runtime.messages.splice(index, 1);
        }
        if (admission?.status === 'queued') {
          toast.info(`消息已排队${admission.queue_position ? ` · 第 ${admission.queue_position} 位` : ''}`);
          onQueueChanged?.();
        }
        if (admission?.status === 'failed') {
          toast.error(admission.error ?? '消息未通过发送校验，请编辑或撤回后重试');
          onQueueChanged?.();
        }
        finalize();
      })
      .catch((err: unknown) => {
        if ((err as { name?: string })?.name === 'AbortError') {
          finalize(undefined, Boolean(getRuntime(sid).turnId));
          return;
        }
        const detached = Boolean(getRuntime(sid).turnId);
        finalize(detached ? undefined : extractErr(err, '连接失败'), detached);
        toast.error(extractErr(err, '发送失败'));
      });
  }, [
    activeSessionId,
    getRuntime,
    bump,
    mode,
    executionMode,
    onQueueChanged,
    onAgentTaskChanged,
    onObjectReferencesConsumed,
  ]);

  const sendMessage = useCallback(
    (
      payload: string,
      questionIndexes: number[] = [],
      attachments: Attachment[] = [],
      objectReferences: ProductObjectReference[] = [],
    ) => {
      // Identity belongs to the user's Send action, not to an HTTP attempt.
      // ``streamChatTurn`` reuses it for every admission retry.
      const submission = createChatSubmissionIdentity();
      startStream(
        payload,
        undefined,
        questionIndexes,
        attachments,
        objectReferences,
        submission,
      );
    },
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
