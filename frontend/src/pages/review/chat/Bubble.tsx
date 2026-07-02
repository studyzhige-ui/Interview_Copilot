import { memo, useCallback, useMemo, useState } from 'react';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { SourceCards, linkifyCitations } from '@/components/chat/SourceCards';
import type { ContentBlock, Source } from '@/types/api';
import type { UIMessage } from './types';
import { BlockChain } from './MessageBlocks';

/**
 * Wrapped in ``React.memo`` so finalized message bubbles in the
 * virtualizer don't re-render every time the parent ticks for
 * streaming progress. Pre-memo the parent re-rendered ~50/sec
 * during a stream, rebuilding every visible bubble's JSX (the
 * heavy markdown work was already short-circuited by MarkdownBody's
 * own memo, but the wrapper churn was still visible in profiler
 * flame graphs as "Bubble" rows). With memo, the inflight bubble
 * (rendered outside the virtualizer) is the only one that re-renders.
 *
 * Default shallow-compare works because finalized messages have
 * stable references: ``rt.messages.push({...})`` captures the
 * inflightBlocks ref into the new message, then ``rt.inflightBlocks
 * = []`` swaps in a fresh array — so the message's ``blocks`` ref
 * never changes after creation.
 */
export const Bubble = memo(function Bubble({ role, content, blocks, sources }: {
  role: UIMessage['role'];
  content: string;
  blocks?: ContentBlock[];
  sources?: Source[];
}) {
  const mine = role === 'user';
  // Clicking a [K#] badge highlights + scrolls to its source card.
  const [highlightRef, setHighlightRef] = useState<string | null>(null);
  const citeRefs = useMemo(
    () => (sources && sources.length ? new Set(sources.map((s) => s.ref)) : null),
    [sources],
  );
  const onCiteClick = useCallback((ref: string) => setHighlightRef(ref), []);
  const cite = citeRefs ? onCiteClick : undefined;
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65]',
          mine
            ? 'bg-primary-500 text-white rounded-2xl rounded-br-sm'
            : role === 'system'
              ? 'bg-warning-50 text-warning-700 border border-warning-200 rounded-2xl'
              : 'bg-stone-50 text-stone-800 border border-stone-200 rounded-2xl rounded-bl-sm',
        ].join(' ')}
      >
        {mine ? (
          <span className="whitespace-pre-wrap">{content}</span>
        ) : blocks && blocks.length > 0 ? (
          <BlockChain blocks={blocks} citeRefs={citeRefs} onCiteClick={cite} />
        ) : (
          <MarkdownBody
            source={citeRefs ? linkifyCitations(content, citeRefs) : content}
            onCiteClick={cite}
          />
        )}
        {!mine && sources && sources.length > 0 && (
          <SourceCards sources={sources} highlightRef={highlightRef} />
        )}
      </div>
    </div>
  );
});
