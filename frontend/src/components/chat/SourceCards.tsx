/**
 * SourceCards — the L1 RAG citation panel under an assistant message.
 *
 * Renders the turn's ``sources`` array (backend §2.7 schema) as compact
 * cards, each labelled with its ``[K#]`` ref. Clicking a ``[K#]`` badge in
 * the answer body scrolls to + highlights the matching card here
 * (``highlightRef`` is driven by the bubble's cite-click handler).
 */
import { useEffect, useRef } from 'react';
import { FileText } from 'lucide-react';
import type { Source } from '@/types/api';

/**
 * One alternation pass: a fenced code block / inline code span, OR a bare
 * ``[K1]`` citation token not already a markdown link (the ``(?!\()``
 * lookahead avoids mangling ``[K1](url)``). The code branch is captured so
 * it can be passed through verbatim — that's how we leave code untouched.
 */
const CODE_OR_CITE = /(```[\s\S]*?```|`[^`]*`)|\[(K\d+)\](?!\()/g;

/**
 * Turn bare ``[K#]`` tokens into in-page citation links
 * (``[K1](#cite-K1)``) so MarkdownBody can render them as click targets.
 * Only refs that actually have a source are linkified — a stray ``[K9]``
 * the model invented stays plain text. Code spans / fenced blocks are left
 * untouched (a ``[K1]`` inside code keeps rendering as ``[K1]``).
 */
export function linkifyCitations(markdown: string, validRefs: Set<string>): string {
  if (!markdown || validRefs.size === 0) return markdown;
  return markdown.replace(CODE_OR_CITE, (whole, code: string | undefined, ref: string) => {
    if (code !== undefined) return code;   // inside code — pass through verbatim
    return validRefs.has(ref) ? `[${ref}](#cite-${ref})` : whole;
  });
}

function pageLabel(s: Source): string | null {
  if (s.page_start == null) return null;
  if (s.page_end != null && s.page_end !== s.page_start) {
    return `p.${s.page_start}-${s.page_end}`;
  }
  return `p.${s.page_start}`;
}

export function SourceCards({
  sources, highlightRef,
}: { sources: Source[]; highlightRef?: string | null }) {
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (highlightRef) {
      cardRefs.current.get(highlightRef)?.scrollIntoView({
        block: 'nearest', behavior: 'smooth',
      });
    }
  }, [highlightRef]);

  if (!sources.length) return null;

  return (
    <div className="mt-2 pt-2 border-t border-stone-200/70">
      <div className="text-[11px] font-medium text-stone-400 mb-1.5">
        引用来源 · {sources.length}
      </div>
      <div className="space-y-1.5">
        {sources.map((s) => {
          const page = pageLabel(s);
          const active = s.ref === highlightRef;
          return (
            <div
              key={s.ref}
              ref={(el) => { if (el) cardRefs.current.set(s.ref, el); }}
              className={[
                'rounded-lg border px-2.5 py-1.5 text-[12px] transition-colors',
                active
                  ? 'border-primary-300 bg-primary-50/60 ring-1 ring-primary-200'
                  : 'border-stone-200 bg-white',
              ].join(' ')}
            >
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="shrink-0 inline-flex items-center px-1.5 rounded bg-primary-100 text-primary-700 font-mono text-[11px]">
                  {s.ref}
                </span>
                <FileText size={12} className="shrink-0 text-stone-400" />
                <span className="truncate font-medium text-stone-700">
                  {s.document_title || s.file_name || '未命名文档'}
                </span>
              </div>
              <div className="flex items-center gap-2 text-[11px] text-stone-400 mb-0.5">
                {s.section_title && <span className="truncate">{s.section_title}</span>}
                {page && <span className="shrink-0">{page}</span>}
                {s.chunk_index != null && <span className="shrink-0">#{s.chunk_index}</span>}
                {s.score != null && (
                  <span className="shrink-0 ml-auto font-mono">{s.score.toFixed(3)}</span>
                )}
              </div>
              {s.text_preview && (
                <p className="text-stone-500 leading-snug line-clamp-2">
                  {s.text_preview}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
