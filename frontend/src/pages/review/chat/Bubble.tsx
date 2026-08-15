import { memo, useCallback, useMemo, useState } from 'react';
import { Check, Copy, FileText, Link2 } from 'lucide-react';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { SourceCards, linkifyCitations } from '@/components/chat/SourceCards';
import type { ContentBlock, Source } from '@/types/api';
import type { UIMessage } from './types';
import { BlockChain, finalAnswerText } from './MessageBlocks';

export const Bubble = memo(function Bubble({
  role,
  content,
  blocks,
  sources,
  sessionId,
  turnId,
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
    <div className={`flex ${mine ? 'justify-end' : 'justify-start'} my-2`}>
      <div
        className={[
          'group max-w-[88%] px-4 py-3 text-[14px] leading-relaxed transition-all',
          mine
            ? 'bg-blue-600 text-white rounded-3xl rounded-br-md shadow-sm shadow-blue-500/15'
            : role === 'system'
              ? 'bg-amber-50 text-amber-900 border border-amber-200/80 rounded-2xl shadow-xs'
              : 'bg-white text-slate-800 border border-slate-200/80 rounded-3xl rounded-bl-md shadow-xs',
        ].join(' ')}
      >
        {mine ? (
          <>
            {attachmentBlocks.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {attachmentBlocks.map((attachment) => (
                  <span
                    key={attachment.type === 'attachment'
                      ? attachment.attachment_ref_id
                      : attachment.draft_id}
                    className="inline-flex max-w-full items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-medium"
                    title={attachment.title}
                  >
                    <FileText size={11} className="shrink-0" />
                    <span className="truncate">{attachment.title}</span>
                  </span>
                ))}
              </div>
            )}
            {objectReferenceBlocks.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5">
                {objectReferenceBlocks.map((reference) => (
                  <span
                    key={`${reference.kind}:${reference.object_id}`}
                    className="inline-flex max-w-full items-center gap-1 rounded-full bg-white/20 px-2.5 py-0.5 text-[11px] font-medium"
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
          <div className="mt-2.5 flex justify-end border-t border-slate-100 pt-1.5">
            <button
              type="button"
              onClick={() => { void copyAnswer(); }}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
              aria-label="复制回答"
              title="复制回答"
            >
              {copied ? <Check size={12} className="text-emerald-600" /> : <Copy size={12} />}
              <span>{copied ? '已复制' : '复制'}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
});
