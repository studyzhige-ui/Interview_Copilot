import { useState } from 'react';
import {
  Wrench, ChevronRight, CheckCircle2, AlertCircle,
} from 'lucide-react';
import { Spinner } from '@/components/ui/Spinner';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { linkifyCitations } from '@/components/chat/SourceCards';
import type { ContentBlock, ToolResultBlock, ToolUseBlock } from '@/types/api';

/**
 * Render a chain of Anthropic-style content blocks. Adjacent
 * ``tool_use`` + ``tool_result`` pairs collapse into a single folded
 * card (Claude-Code style) so a ReAct turn reads as: text → [🔧 card]
 * → text → [🔧 card] → final text.
 */
export function BlockChain({ blocks, citeRefs, onCiteClick }: {
  blocks: ContentBlock[];
  /** When set, [K#] tokens in text blocks become clickable citation
   *  badges resolving to ``onCiteClick``. Agent turns omit both. */
  citeRefs?: Set<string> | null;
  onCiteClick?: (ref: string) => void;
}) {
  const out: React.ReactNode[] = [];
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
      const result = next && next.type === 'tool_result' ? next : null;
      out.push(<ToolCard key={`b${i}`} use={b} result={result} />);
      i += result ? 2 : 1;
      continue;
    }
    if (b.type === 'tool_result') {
      // Orphaned tool_result (no preceding tool_use) — shouldn't happen
      // with the current backend but render defensively.
      out.push(<ToolCard key={`b${i}`} use={null} result={b} />);
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
  use, result,
}: { use: ToolUseBlock | null; result: ToolResultBlock | null }) {
  const [open, setOpen] = useState(false);
  const name = use?.name ?? '(unknown tool)';
  const summary = result?.summary ?? '';
  const isError = !!result?.is_error;
  const pending = !result;   // tool_start fired but tool_done not yet
  const latencyMs = result?.latency_ms;
  const Icon = pending ? Wrench : isError ? AlertCircle : CheckCircle2;
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
        </div>
      )}
    </div>
  );
}
