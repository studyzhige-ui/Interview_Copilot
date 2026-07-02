import { Sparkles } from 'lucide-react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Spinner } from '@/components/ui/Spinner';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { SourceCards } from '@/components/chat/SourceCards';
import type { ContentBlock, Source } from '@/types/api';
import type { UIMessage } from './types';
import { Bubble } from './Bubble';
import { BlockChain } from './MessageBlocks';

/**
 * Virtualized message list + empty states + the live streaming bubble.
 *
 * The streaming bubble renders OUTSIDE the virtualizer (it changes every
 * animation frame; finalized bubbles are memoized and only re-render on
 * message identity change).
 */
export function MessageList({
  listRef,
  activeSessionId,
  externalMode,
  messages,
  partial,
  inflightBlocks,
  inflightSources,
  statusHint,
  streaming,
  hidePartialBar,
  onTogglePartialBar,
}: {
  listRef: React.MutableRefObject<HTMLDivElement | null>;
  activeSessionId: string | null;
  externalMode: boolean;
  messages: UIMessage[];
  partial: string;
  inflightBlocks: ContentBlock[];
  inflightSources: Source[];
  statusHint: string;
  streaming: boolean;
  hidePartialBar: boolean;
  onTogglePartialBar: (hidden: boolean) => void;
}) {
  const messageVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => listRef.current,
    estimateSize: () => 96,
    overscan: 6,
    getItemKey: (index) => `${activeSessionId ?? 'none'}:${index}`,
  });

  return (
    <div ref={listRef} className="flex-1 min-h-0 overflow-y-auto p-4 relative">
      {!activeSessionId && (
        <div className="absolute inset-0 flex items-center justify-center text-stone-400 px-6">
          <div className="text-center">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-sm text-stone-500 font-medium mb-1">
              {externalMode ? '先在左侧选择一项' : '该面试还没有会话'}
            </div>
            <div className="text-xs leading-relaxed">
              {externalMode ? '选中后会自动开始一段对话' : '点右上「+ 新会话」开始一段对话'}
            </div>
          </div>
        </div>
      )}
      {activeSessionId && messages.length === 0 && !streaming && (
        <div className="absolute inset-0 flex items-center justify-center text-stone-400 px-6">
          <div className="text-center">
            <div className="w-11 h-11 mx-auto rounded-2xl bg-stone-100 text-stone-400 flex items-center justify-center mb-3">
              <Sparkles size={18} />
            </div>
            <div className="text-sm text-stone-500 font-medium mb-1">说点什么开始对话</div>
            <div className="text-xs leading-relaxed">输入消息后会看到流式生成的回答</div>
          </div>
        </div>
      )}
      <div style={{ height: messageVirtualizer.getTotalSize() }} className="relative">
        {messageVirtualizer.getVirtualItems().map((vi) => {
          const m = messages[vi.index];
          return (
            <div
              key={vi.key}
              ref={messageVirtualizer.measureElement}
              data-index={vi.index}
              style={{ position: 'absolute', top: 0, left: 0, right: 0, transform: `translateY(${vi.start}px)` }}
            >
              <div className="pb-3">
                <Bubble role={m.role} content={m.content} blocks={m.blocks} sources={m.sources} />
              </div>
            </div>
          );
        })}
      </div>
      {streaming && !hidePartialBar && (
        <div className="flex justify-start">
          <div className="max-w-[85%] px-3.5 py-2.5 text-[14px] leading-[1.65] bg-stone-50 border border-stone-200 rounded-2xl">
            {/* Tool cards & finalized text blocks accumulated so far
                for this in-flight assistant turn. Same renderer as
                the persisted assistant bubble — what you see during
                streaming matches what you see after refresh. */}
            {inflightBlocks.length > 0 && (
              <BlockChain blocks={inflightBlocks} />
            )}
            {/* Live typing tail. ``partial`` is what hasn't yet been
                flushed into a finalized text block. */}
            {partial ? (
              <MarkdownBody source={partial} />
            ) : inflightBlocks.length === 0 ? (
              <span className="text-stone-400 inline-flex items-center gap-1.5">
                <Spinner size={10} className="text-primary-500" />
                {statusHint || 'AI 正在生成…'}
              </span>
            ) : null}
            {/* Sources arrive before the first token — show the panel
                early so the user sees provenance as the answer streams.
                [K#] become clickable once the turn finalizes. */}
            {inflightSources.length > 0 && (
              <SourceCards sources={inflightSources} />
            )}
            <button
              onClick={() => onTogglePartialBar(true)}
              className="ml-2 text-[11px] text-stone-400 hover:text-stone-600"
            >
              收起
            </button>
          </div>
        </div>
      )}
      {streaming && hidePartialBar && (
        <div className="flex justify-start">
          <button
            onClick={() => onTogglePartialBar(false)}
            className="rounded-full bg-primary-50 text-primary-700 text-xs px-3 py-1 inline-flex items-center gap-1.5 hover:bg-primary-100 border border-primary-100"
            title="展开流式生成"
          >
            <Spinner size={10} className="text-primary-500" />
            {statusHint || 'AI 正在后台生成…'} · 点击展开
          </button>
        </div>
      )}
    </div>
  );
}
