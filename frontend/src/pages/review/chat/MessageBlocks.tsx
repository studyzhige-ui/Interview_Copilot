import { useState } from 'react';
import {
  Wrench, ChevronRight, CheckCircle2, AlertCircle,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { linkifyCitations } from '@/components/chat/SourceCards';
import { getToolCallAudit } from '@/api/chat';
import type {
  AgentToolCallAudit, ContentBlock, ToolResultBlock, ToolUseBlock,
} from '@/types/api';

/**
 * Render an Anthropic-style block chain. Tool uses/results are paired by
 * their durable call id, not adjacency: parallel completions may arrive in a
 * different order while still belonging to the same call card.
 */
export function BlockChain({
  blocks, citeRefs, onCiteClick, auditRef, collapseTools = false,
}: {
  blocks: ContentBlock[];
  /** When set, [K#] tokens in text blocks become clickable citation
   *  badges resolving to ``onCiteClick``. Agent turns omit both. */
  citeRefs?: Set<string> | null;
  onCiteClick?: (ref: string) => void;
  auditRef?: { sessionId: string; turnId: string };
  collapseTools?: boolean;
}) {
  const out: Array<{
    kind: 'content' | 'tool';
    key: string;
    node: React.ReactNode;
    pending?: boolean;
    isError?: boolean;
  }> = [];
  const resultByCallId = new Map<string, { result: ToolResultBlock; index: number }>();
  blocks.forEach((block, index) => {
    if (block.type === 'tool_result' && block.tool_use_id && !resultByCallId.has(block.tool_use_id)) {
      resultByCallId.set(block.tool_use_id, { result: block, index });
    }
  });
  const pairedResultIndexes = new Set<number>();
  blocks.forEach((block) => {
    if (block.type !== 'tool_use' || !block.id) return;
    const match = resultByCallId.get(block.id);
    if (match) pairedResultIndexes.add(match.index);
  });
  let i = 0;
  while (i < blocks.length) {
    const b = blocks[i];
    if (b.type === 'text') {
      out.push({
        kind: 'content',
        key: `b${i}`,
        node: <div key={`b${i}`} className="prose-block">
          <MarkdownBody
            source={citeRefs ? linkifyCitations(b.text, citeRefs) : b.text}
            onCiteClick={onCiteClick}
          />
        </div>,
      });
      i += 1;
      continue;
    }
    if (b.type === 'tool_use') {
      const next = blocks[i + 1];
      // Empty ids are only possible for old live events; preserve the old
      // adjacent fallback without weakening id-based replay pairing.
      const adjacentLegacyResult = !b.id && next?.type === 'tool_result'
        ? next
        : null;
      const result = b.id
        ? resultByCallId.get(b.id)?.result ?? null
        : adjacentLegacyResult;
      out.push({
        kind: 'tool',
        key: b.id || `b${i}`,
        pending: !result,
        isError: Boolean(result?.is_error),
        node: <ToolCard
          key={b.id || `b${i}`}
          use={b}
          result={result}
          auditRef={auditRef}
        />,
      });
      i += adjacentLegacyResult ? 2 : 1;
      continue;
    }
    if (b.type === 'tool_result') {
      if (pairedResultIndexes.has(i)) {
        i += 1;
        continue;
      }
      // Preserve an unmatched result instead of silently dropping History.
      out.push({
        kind: 'tool',
        key: `b${i}`,
        isError: Boolean(b.is_error),
        node: <ToolCard key={`b${i}`} use={null} result={b} auditRef={auditRef} />,
      });
      i += 1;
      continue;
    }
    i += 1;  // unknown block type — skip
  }
  if (!collapseTools) return <>{out.map((item) => item.node)}</>;

  // A completed answer owns one process disclosure, not one disclosure per
  // contiguous run of Tool cards.  Everything up to the last Tool result is
  // execution narration; text after that boundary is the final answer.  This
  // mirrors the live stream while keeping the settled message calm by default.
  let lastToolIndex = -1;
  for (let index = out.length - 1; index >= 0; index -= 1) {
    if (out[index].kind === 'tool') {
      lastToolIndex = index;
      break;
    }
  }
  if (lastToolIndex < 0) return <>{out.map((item) => item.node)}</>;
  const processItems = out.slice(0, lastToolIndex + 1);
  const finalItems = out.slice(lastToolIndex + 1);
  return (
    <>
      <ExecutionTraceGroup items={processItems} />
      {finalItems.map((item) => item.node)}
    </>
  );
}

export function finalAnswerText(blocks: ContentBlock[], fallback = ''): string {
  let lastExecutionIndex = -1;
  blocks.forEach((block, index) => {
    if (block.type === 'tool_use' || block.type === 'tool_result') {
      lastExecutionIndex = index;
    }
  });
  const answerBlocks = blocks
    .slice(lastExecutionIndex + 1)
    .filter((block): block is Extract<ContentBlock, { type: 'text' }> => block.type === 'text')
    .map((block) => block.text.trim())
    .filter(Boolean);
  return answerBlocks.length ? answerBlocks.join('\n\n') : fallback.trim();
}

function ExecutionTraceGroup({ items }: {
  items: Array<{
    kind: 'content' | 'tool';
    key: string;
    node: React.ReactNode;
    pending?: boolean;
    isError?: boolean;
  }>;
}) {
  const pending = items.some((item) => item.pending);
  const toolItems = items.filter((item) => item.kind === 'tool');
  const errors = toolItems.filter((item) => item.isError).length;
  const [open, setOpen] = useState(pending);
  return (
    <section className="my-2 overflow-hidden rounded-lg border border-stone-200 bg-stone-50/80">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-stone-600 hover:bg-stone-100"
      >
        <ChevronRight
          size={13}
          className={`shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}
        />
        <Wrench size={13} className="shrink-0 text-stone-500" />
        <span className="font-medium text-stone-700">执行过程</span>
        <span className="text-stone-400">{toolItems.length} 次工具调用</span>
        <span className={`ml-auto ${errors ? 'text-danger-600' : pending ? 'text-stone-500' : 'text-accent-700'}`}>
          {errors ? `${errors} 次失败` : pending ? '执行中' : '已完成'}
        </span>
      </button>
      {open && <div className="border-t border-stone-200 px-2 py-1">{items.map((item) => item.node)}</div>}
    </section>
  );
}

/**
 * Folded tool call card. Header always shows "🔧 name · summary";
 * click to expand input (JSON args) + full result content.
 */
function ToolCard({
  use, result, auditRef,
}: {
  use: ToolUseBlock | null;
  result: ToolResultBlock | null;
  auditRef?: { sessionId: string; turnId: string };
}) {
  const [open, setOpen] = useState(false);
  const [audit, setAudit] = useState<AgentToolCallAudit | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState('');
  const name = use?.name ?? '(unknown tool)';
  const summary = result?.summary ?? '';
  const isError = !!result?.is_error;
  const pending = !result;   // tool_start fired but tool_done not yet
  const latencyMs = result?.latency_ms;
  const Icon = pending ? Wrench : isError ? AlertCircle : CheckCircle2;
  const canAudit = Boolean(auditRef && use?.id);
  const loadAudit = async () => {
    if (!auditRef || !use?.id || auditLoading) return;
    setAuditLoading(true);
    setAuditError('');
    try {
      setAudit(await getToolCallAudit(auditRef.sessionId, auditRef.turnId, use.id));
    } catch {
      setAuditError('执行审计暂时不可用');
    } finally {
      setAuditLoading(false);
    }
  };
  return (
    <div
      className={[
        'my-1.5 rounded-lg border text-[12px] font-mono leading-snug',
        isError
          ? 'bg-danger-50 border-danger-200'
          : pending
            ? 'bg-stone-50 border-stone-200'
            : 'bg-accent-50/50 border-accent-100',
      ].join(' ')}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        className={[
          'w-full flex items-center gap-1.5 px-2.5 py-1.5 text-left',
          'hover:bg-black/[0.02] rounded-lg',
        ].join(' ')}
      >
        <ChevronRight
          size={12}
          className={['shrink-0 text-stone-400 transition-transform',
            open ? 'rotate-90' : ''].join(' ')}
        />
        <Icon
          size={12}
          className={[
            'shrink-0',
            isError ? 'text-danger-600'
              : pending ? 'text-stone-400'
              : 'text-accent-700',
          ].join(' ')}
        />
        <span className="font-semibold text-stone-700">{name}</span>
        {summary && (
          <span className="text-stone-500 truncate">· {summary}</span>
        )}
        {pending && (
          <Spinner size={10} className="ml-auto text-stone-400 shrink-0" />
        )}
        {!pending && typeof latencyMs === 'number' && (
          <span className="ml-auto shrink-0 text-stone-400 text-[10px]">
            {latencyMs >= 1000
              ? `${(latencyMs / 1000).toFixed(1)}s`
              : latencyMs < 1
                ? '<1ms'
                : `${Math.round(latencyMs)}ms`}
          </span>
        )}
      </button>
      {open && (
        <div className="px-2.5 pb-2 space-y-1.5">
          {use && Object.keys(use.input).length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-stone-400 mb-0.5">
                Input
              </div>
              <pre className="bg-white border border-stone-200 rounded p-2 text-[11px] overflow-x-auto whitespace-pre-wrap break-words">
                {JSON.stringify(use.input, null, 2)}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-stone-400 mb-0.5">
                {isError ? 'Error' : 'Output'}
              </div>
              <pre className={[
                'border rounded p-2 text-[11px] overflow-x-auto whitespace-pre-wrap break-words',
                isError
                  ? 'bg-white border-danger-200 text-danger-700'
                  : 'bg-white border-stone-200',
              ].join(' ')}>
                {result.content || '(刷新会话以加载完整输出)'}
              </pre>
            </div>
          )}
          {canAudit && !audit && (
            <button
              type="button"
              onClick={() => { void loadAudit(); }}
              disabled={auditLoading}
              className="text-[11px] text-primary-700 hover:text-primary-800 disabled:text-stone-400"
            >
              {auditLoading ? '正在读取执行审计…' : '查看执行审计'}
            </button>
          )}
          {auditError && <div className="text-[11px] text-danger-700">{auditError}</div>}
          {audit && (
            <section
              aria-label={`执行审计 ${audit.call_id}`}
              className="space-y-1.5 rounded border border-stone-200 bg-white p-2 text-[11px]"
            >
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-stone-600">
                <span>状态：{audit.status}</span>
                <span>影响：{audit.effect}</span>
                <span>Policy：{audit.policy_decision}</span>
                <span>原因：{audit.policy_reason}</span>
                <span>执行代次：{audit.dispatch_generation}</span>
                <span>耗时：{audit.duration_ms == null ? '—' : `${Math.round(audit.duration_ms)}ms`}</span>
              </div>
              <div className="text-stone-500 break-all">Call ID：{audit.call_id}</div>
              <details>
                <summary className="cursor-pointer text-stone-600">已脱敏参数与结果</summary>
                <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded bg-stone-50 p-2">
                  {JSON.stringify({
                    arguments: audit.arguments,
                    result: audit.result,
                    error: audit.error,
                    started_at: audit.started_at,
                    completed_at: audit.completed_at,
                  }, null, 2)}
                </pre>
              </details>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
