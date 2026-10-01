import { describe, expect, it } from 'vitest';
import { invitationDraft } from './InvitationFields';

describe('canonical nullable candidate facts', () => {
  it('preserves missing candidate values without inventing its timezone', () => {
    const draft = invitationDraft({ company_name: null, job_title: 'Engineer', source_timezone: null });
    expect(draft.company_name).toBe('');
    expect(draft.job_title).toBe('Engineer');
    expect(draft.source_timezone).toBe('');
    expect(invitationDraft({}).source_timezone).toBe('');
  });
  it('suggests the browser timezone only for a new explicit manual form', () => {
    expect(invitationDraft().source_timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
    expect(invitationDraft({ source_timezone: 'Asia/Shanghai' }).source_timezone).toBe('Asia/Shanghai');
  });
});
