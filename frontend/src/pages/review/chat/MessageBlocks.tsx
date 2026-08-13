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
export function BlockChain({ blocks, citeRefs, onCiteClick, auditRef }: {
  blocks: ContentBlock[];
  /** When set, [K#] tokens in text blocks become clickable citation
   *  badges resolving to ``onCiteClick``. Agent turns omit both. */
  citeRefs?: Set<string> | null;
  onCiteClick?: (ref: string) => void;
  auditRef?: { sessionId: string; turnId: string };
}) {
  const out: React.ReactNode[] = [];
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
      out.push(
        <div key={`b${i}`} className="prose-block">
          <MarkdownBody
            source={citeRefs ? linkifyCitations(b.text, citeRefs) : b.text}
            onCiteClick={onCiteClick}
          />
        </div>
      );
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
      out.push(
        <ToolCard
          key={b.id || `b${i}`}
          use={b}
          result={result}
          auditRef={auditRef}
        />,
      );
      i += adjacentLegacyResult ? 2 : 1;
      continue;
    }
    if (b.type === 'tool_result') {
      if (pairedResultIndexes.has(i)) {
        i += 1;
        continue;
      }
      // Preserve an unmatched result instead of silently dropping History.
      out.push(<ToolCard key={`b${i}`} use={null} result={b} auditRef={auditRef} />);
      i += 1;
      continue;
    }
    i += 1;  // unknown block type — skip
  }
  return <>{out}</>;
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
