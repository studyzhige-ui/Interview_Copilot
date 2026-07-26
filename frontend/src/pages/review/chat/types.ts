import type { ChatMessageItem, ContentBlock, Source } from '@/types/api';

export interface UIMessage {
  role: 'user' | 'assistant' | 'system';
  /** Flat-text rendering for user / system messages and as a fallback
   *  for assistant messages with no ``blocks``. */
  content: string;
  /** Anthropic-style block chain for assistant turns. When present,
   *  the renderer uses these and ignores ``content``. */
  blocks?: ContentBlock[];
  /** L1 RAG citation sources for the turn — drives the source-card panel
   *  and [K#] resolution. Absent for user / system / non-RAG turns. */
  sources?: Source[];
}

export interface Attachment { doc_id: string; filename: string; }

export type Mode = 'CHAT' | 'AGENT';

export interface SessionRuntime {
  abort: AbortController | null;  // in-flight SSE aborter (null between turns)
  turnId: string | null;
  messages: UIMessage[];
  /** Streaming-only state — text being typed RIGHT NOW that hasn't
   *  yet been flushed into ``inflightBlocks`` as a finalized text block. */
  partial: string;
  /** Streaming-only state — finalized blocks for the assistant message
   *  currently being built. Becomes the assistant UIMessage's ``blocks``
   *  on ``finalize``. */
  inflightBlocks: ContentBlock[];
  /** Streaming-only state — RAG sources from the ``sources`` SSE event
   *  (arrives before the first token). Attached to the assistant message
   *  on ``finalize``. */
  inflightSources: Source[];
  status: string;
  streaming: boolean;
  hidePartialBar: boolean;
  loadedHistory: boolean;
}

export function toUI(m: ChatMessageItem): UIMessage {
  const r = (m.role ?? '').toLowerCase();
  // /chat/transcript always sets ``blocks`` (legacy rows are synthesised
  // into a single-text-block array server-side). Pass through unchanged
  // so the renderer can branch uniformly.
  if (r === 'user') return { role: 'user', content: m.content };
  if (r === 'assistant' || r === 'agent' || r === 'ai' || r === 'bot') {
    // The persisted RAG sources ride in a ``{type:"sources"}`` block —
    // lift it out so the source-card panel can consume it (BlockChain
    // skips it when rendering the answer body).
    const sourcesBlock = m.blocks?.find((b) => b.type === 'sources');
    const sources = sourcesBlock?.type === 'sources' ? sourcesBlock.sources : undefined;
    return { role: 'assistant', content: m.content, blocks: m.blocks, sources };
  }
  return { role: 'system', content: m.content };
}
