import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { SourceCards, linkifyCitations } from './SourceCards';
import type { Source } from '@/types/api';

function makeSource(over: Partial<Source> = {}): Source {
  return {
    ref: 'K1',
    chunk_id: 'dch_1',
    node_id: 'n1',
    document_id: 'kdoc_1',
    document_title: 'Redis 面试题',
    file_name: 'redis.pdf',
    category: '面试题库',
    source_kind: 'user_upload',
    page_start: null,
    page_end: null,
    section_title: null,
    heading_path: null,
    chunk_index: 0,
    score: 0.873,
    score_source: 'reranker',
    text_preview: 'Redis 缓存击穿是指……',
    ...over,
  };
}

describe('linkifyCitations', () => {
  it('links only refs that exist in sources', () => {
    const out = linkifyCitations('见 [K1] 和 [K9]。', new Set(['K1']));
    expect(out).toContain('[K1](#cite-K1)');
    // K9 isn't a real source — left as plain text, not linkified.
    expect(out).toContain('[K9]');
    expect(out).not.toContain('#cite-K9');
  });

  it('does not double-link an existing markdown link', () => {
    const out = linkifyCitations('[K1](http://x)', new Set(['K1']));
    expect(out).toBe('[K1](http://x)');
  });

  it('is a no-op with no valid refs', () => {
    const md = 'plain [K1] text';
    expect(linkifyCitations(md, new Set())).toBe(md);
  });

  it('linkifies multiple occurrences', () => {
    const out = linkifyCitations('[K1] then [K2] then [K1]', new Set(['K1', 'K2']));
    expect(out).toBe('[K1](#cite-K1) then [K2](#cite-K2) then [K1](#cite-K1)');
  });
});

describe('SourceCards', () => {
  it('renders one card per source with its ref + title', () => {
    render(<SourceCards sources={[makeSource(), makeSource({ ref: 'K2', document_title: '缓存笔记' })]} />);
    expect(screen.getByText('K1')).toBeInTheDocument();
    expect(screen.getByText('K2')).toBeInTheDocument();
    expect(screen.getByText('Redis 面试题')).toBeInTheDocument();
    expect(screen.getByText('缓存笔记')).toBeInTheDocument();
    expect(screen.getByText('引用来源 · 2')).toBeInTheDocument();
  });

  it('renders a page range when both ends present', () => {
    render(<SourceCards sources={[makeSource({ page_start: 3, page_end: 5 })]} />);
    expect(screen.getByText('p.3-5')).toBeInTheDocument();
  });

  it('renders a single page when start only', () => {
    render(<SourceCards sources={[makeSource({ page_start: 3 })]} />);
    expect(screen.getByText('p.3')).toBeInTheDocument();
  });

  it('falls back to the file name when no title', () => {
    render(<SourceCards sources={[makeSource({ document_title: null, file_name: 'notes.md' })]} />);
    expect(screen.getByText('notes.md')).toBeInTheDocument();
  });

  it('renders nothing for an empty list', () => {
    const { container } = render(<SourceCards sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
