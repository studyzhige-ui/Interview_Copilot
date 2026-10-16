import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { ActionAgenda } from '@/pages/career/ActionAgenda';
import { editNextAction } from '@/api/careerProcess';
import { getNextActionAgenda } from '@/api/careerInsights';
import type { NextAction } from '@/types/career';

vi.mock('@/api/careerProcess', () => ({
  createNextAction: vi.fn(), editNextAction: vi.fn(), transitionNextAction: vi.fn(),
  listJobOpportunities: vi.fn().mockResolvedValue([]), listNextActions: vi.fn().mockResolvedValue([]),
}));
vi.mock('@/api/careerInsights', () => ({ getNextActionAgenda: vi.fn() }));
vi.mock('@/api/offers', () => ({ listCurrentOffers: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/artifacts', () => ({ listAllArtifacts: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/interview', () => ({ listAllInterviewRecords: vi.fn().mockResolvedValue([]) }));

beforeEach(() => vi.clearAllMocks());

it.each(['flexible', 'deadline'] as const)('replaces fixed scheduling when edited to %s', async (timeKind) => {
  const action: NextAction = {
    id: 'na_fixture', user_id: 1, content: '准备项目介绍', status: 'planned', version: 1,
    time_kind: 'fixed', starts_at: '2030-10-14T10:00:00Z', ends_at: '2030-10-14T11:00:00Z',
    due_at: null, original_time_text: '2030-10-14 18:00', source_timezone: 'Asia/Shanghai',
    source_kind: 'user_request', source_identity: 'fixture', source_version: null,
    job_opportunity_id: null, interview_record_id: null, offer_id: null, artifact_id: null,
    reminder_at: null, reminder_channel: null, created_at: '2030-10-01T00:00:00Z', updated_at: '2030-10-01T00:00:00Z',
    planned_at: null, resolved_at: null, close_reason: null, reminder_next_attempt_at: null,
    reminder_delivered_at: null, reminder_dismissed_at: null,
  };
  vi.mocked(getNextActionAgenda).mockResolvedValue({ items: [{ action, bucket: 'upcoming', overdue: false, due_soon: false, conflict_action_ids: [], duplicate_action_ids: [] }], generated_at: '2030-10-01T00:00:00Z' });
  vi.mocked(editNextAction).mockResolvedValue(action);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><ActionAgenda /></MemoryRouter></QueryClientProvider>);
  fireEvent.click(await screen.findByRole('button', { name: '编辑' }));
  fireEvent.change(screen.getByRole('combobox', { name: '时间类型' }), { target: { value: timeKind } });
  if (timeKind === 'deadline') fireEvent.change(screen.getByLabelText('截止时间'), { target: { value: '2030-10-15T18:00' } });
  fireEvent.click(screen.getByRole('button', { name: '保存行动' }));
  await waitFor(() => expect(editNextAction).toHaveBeenCalledOnce());
  const saved = vi.mocked(editNextAction).mock.calls[0][0];
  expect(saved.starts_at).toBeUndefined();
  expect(saved.ends_at).toBeUndefined();
  expect(saved.time_kind).toBe(timeKind);
  if (timeKind === 'deadline') expect(saved.due_at).toBe(new Date('2030-10-15T18:00').toISOString());
  else expect(saved.due_at).toBeUndefined();
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
