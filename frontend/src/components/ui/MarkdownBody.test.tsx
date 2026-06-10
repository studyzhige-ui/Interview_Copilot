import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { MarkdownBody } from './MarkdownBody';

describe('MarkdownBody citations', () => {
  it('renders #cite- anchors as a clickable badge when onCiteClick is set', () => {
    const onCite = vi.fn();
    render(<MarkdownBody source="见 [K1](#cite-K1)" onCiteClick={onCite} />);
    const badge = screen.getByText('K1');
    expect(badge.tagName).toBe('BUTTON');
    fireEvent.click(badge);
    expect(onCite).toHaveBeenCalledWith('K1');
  });

  it('renders #cite- anchors as a plain anchor when no onCiteClick', () => {
    render(<MarkdownBody source="见 [K1](#cite-K1)" />);
    const el = screen.getByText('K1');
    // No callback → falls through to the normal link branch, not a badge.
    expect(el.tagName).toBe('A');
  });

  it('leaves real external links as anchors even with onCiteClick set', () => {
    render(<MarkdownBody source="[docs](https://example.com)" onCiteClick={vi.fn()} />);
    const link = screen.getByText('docs');
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('https://example.com');
    expect(link.getAttribute('rel')).toContain('noopener');
  });
});
