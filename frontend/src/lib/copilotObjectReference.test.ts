import { describe, expect, it } from 'vitest';
import {
  clearCopilotObjectHandoff,
  copilotObjectHandoffHref,
  readCopilotObjectHandoff,
} from './copilotObjectReference';

describe('Copilot product-object handoff', () => {
  it('round-trips the closed identity and keeps the label display-only', () => {
    const href = copilotObjectHandoffHref(
      'artifact',
      'art_1',
      '简历 & 求职信',
    );
    const parsed = readCopilotObjectHandoff(
      new URLSearchParams(href.split('?')[1]),
    );
    expect(parsed).toEqual({
      kind: 'artifact',
      object_id: 'art_1',
      label: '简历 & 求职信',
    });
  });

  it('fails closed for unknown kinds and clears only handoff params', () => {
    const params = new URLSearchParams(
      'object_kind=universal&object_id=x&object_label=X&gmail_oauth_outcome=connected',
    );
    expect(readCopilotObjectHandoff(params)).toBeNull();
    expect(clearCopilotObjectHandoff(params).toString()).toBe(
      'gmail_oauth_outcome=connected',
    );
  });
});
