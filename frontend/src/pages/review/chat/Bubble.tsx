import { memo, useCallback, useMemo, useState } from 'react';
import { Check, Copy, FileText, Link2 } from 'lucide-react';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { SourceCards, linkifyCitations } from '@/components/chat/SourceCards';
import type { ContentBlock, Source } from '@/types/api';
import type { UIMessage } from './types';
import { BlockChain, finalAnswerText } from './MessageBlocks';

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
export const Bubble = memo(function Bubble({
  role, content, blocks, sources, sessionId, turnId,
}: {
  role: UIMessage['role'];
  content: string;
  blocks?: ContentBlock[];
  sources?: Source[];
  sessionId?: string | null;
  turnId?: string | null;
}) {
  const mine = role === 'user';
  const attachmentBlocks = blocks?.filter(
    (block) => block.type === 'attachment' || block.type === 'attachment_draft',
  ) ?? [];
  const objectReferenceBlocks = blocks?.filter(
    (block) => block.type === 'product_object_reference',
  ) ?? [];
  // Clicking a [K#] badge highlights + scrolls to its source card.
  const [highlightRef, setHighlightRef] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const citeRefs = useMemo(
    () => (sources && sources.length ? new Set(sources.map((s) => s.ref)) : null),
    [sources],
  );
  const onCiteClick = useCallback((ref: string) => setHighlightRef(ref), []);
  const cite = citeRefs ? onCiteClick : undefined;
  const answerText = useMemo(
    () => (blocks?.length ? finalAnswerText(blocks, content) : content.trim()),
    [blocks, content],
  );
  const copyAnswer = useCallback(async () => {
    if (!answerText) return;
    await navigator.clipboard.writeText(answerText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }, [answerText]);
  return (
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
      <div
        className={[
          'group max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65]',
          mine
            ? 'bg-primary-500 text-white rounded-2xl rounded-br-sm'
            : role === 'system'
              ? 'bg-warning-50 text-warning-700 border border-warning-200 rounded-2xl'
              : 'bg-stone-50 text-stone-800 border border-stone-200 rounded-2xl rounded-bl-sm',
        ].join(' ')}
      >
        {mine ? (
          <>
            {attachmentBlocks.length > 0 && (
              <div className="mb-1.5 flex flex-wrap gap-1">
                {attachmentBlocks.map((attachment) => (
                  <span
                    key={attachment.type === 'attachment'
                      ? attachment.attachment_ref_id
                      : attachment.draft_id}
                    className="inline-flex max-w-full items-center gap-1 rounded-md bg-white/15 px-2 py-1 text-[11px]"
                    title={attachment.title}
                  >
                    <FileText size={11} className="shrink-0" />
                    <span className="truncate">{attachment.title}</span>
                  </span>
                ))}
              </div>
            )}
            {objectReferenceBlocks.length > 0 && (
              <div className="mb-1.5 flex flex-wrap gap-1">
                {objectReferenceBlocks.map((reference) => (
                  <span
                    key={`${reference.kind}:${reference.object_id}`}
                    className="inline-flex max-w-full items-center gap-1 rounded-md bg-white/15 px-2 py-1 text-[11px]"
                    title={`${reference.kind} · ${reference.object_id}`}
                  >
                    <Link2 size={11} className="shrink-0" />
                    <span className="truncate">{reference.label}</span>
                  </span>
                ))}
              </div>
            )}
            <span className="whitespace-pre-wrap">{content}</span>
          </>
        ) : blocks && blocks.length > 0 ? (
          <BlockChain
            blocks={blocks}
            citeRefs={citeRefs}
            onCiteClick={cite}
            auditRef={sessionId && turnId ? { sessionId, turnId } : undefined}
            collapseTools
          />
        ) : (
          <MarkdownBody
            source={citeRefs ? linkifyCitations(content, citeRefs) : content}
            onCiteClick={cite}
          />
        )}
        {!mine && sources && sources.length > 0 && (
          <SourceCards sources={sources} highlightRef={highlightRef} />
        )}
        {role === 'assistant' && answerText && (
          <div className="mt-2 flex justify-end border-t border-stone-200/70 pt-1.5">
            <button
              type="button"
              onClick={() => { void copyAnswer(); }}
              className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-[11px] text-stone-400 transition hover:bg-white hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
              aria-label="复制回答"
              title="复制回答"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? '已复制' : '复制'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
});
