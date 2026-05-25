import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';

import { Pill } from './Pill';

describe('Pill', () => {
  it('renders its children inside a span', () => {
    render(<Pill>Hello</Pill>);
    const el = screen.getByText('Hello');
    expect(el).toBeInTheDocument();
    expect(el.tagName).toBe('SPAN');
  });

  it('applies the neutral tone class by default', () => {
    render(<Pill>x</Pill>);
    const el = screen.getByText('x');
    expect(el.className).toContain('bg-stone-100');
    expect(el.className).toContain('text-stone-700');
  });

  it('applies the requested tone class', () => {
    render(<Pill tone="danger">x</Pill>);
    const el = screen.getByText('x');
    expect(el.className).toContain('bg-danger-50');
    expect(el.className).toContain('text-danger-700');
  });
});
