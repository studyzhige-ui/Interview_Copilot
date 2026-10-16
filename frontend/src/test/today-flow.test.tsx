import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { TodayPage } from '@/pages/today/TodayPage';
import { getNextActionAgenda } from '@/api/careerInsights';
import { getWorkspaceOverview } from '@/api/workspace';
import { listPendingConfirmations, type PendingConfirmation } from '@/api/interviewInvitations';
import type { NextAction } from '@/types/career';

vi.mock('@/api/careerInsights', () => ({ getNextActionAgenda: vi.fn() }));
vi.mock('@/api/workspace', () => ({ getWorkspaceOverview: vi.fn() }));
vi.mock('@/api/interviewInvitations', () => ({ listPendingConfirmations: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getWorkspaceOverview).mockResolvedValue({ has_resume: false, active_opportunities: 0, open_actions: 0, recent_work: [], upcoming_interviews: [] });
  vi.mocked(getNextActionAgenda).mockResolvedValue({ generated_at: new Date().toISOString(), items: [] });
  vi.mocked(listPendingConfirmations).mockResolvedValue([]);
});
function show() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter><TodayPage /></MemoryRouter></QueryClientProvider>);
}

it('surfaces a confirmed Offer deadline and links directly to its actionable view', async () => {
  const action: NextAction = {
    id: 'deadline', user_id: 1, content: '回复 Offer', status: 'suggested', version: 1,
    time_kind: 'deadline', starts_at: null, ends_at: null, due_at: new Date().toISOString(),
    original_time_text: null, source_timezone: null, source_kind: 'offer', source_identity: 'fixture', source_version: null,
    job_opportunity_id: null, interview_record_id: null, offer_id: 'offer', artifact_id: null,
    reminder_at: null, reminder_channel: null, created_at: '', updated_at: '', planned_at: null, resolved_at: null, close_reason: null,
    reminder_next_attempt_at: null, reminder_delivered_at: null, reminder_dismissed_at: null,
  };
  vi.mocked(getNextActionAgenda).mockResolvedValue({ generated_at: '', items: [{ action, bucket: 'suggested', overdue: true, due_soon: true, conflict_action_ids: [], duplicate_action_ids: [] }] });
  show();
  expect(await screen.findByRole('link', { name: /回复 Offer/ })).toHaveAttribute('href', '/career-calendar?view=actions#action-deadline');
  expect(screen.getByRole('link', { name: /管理全部安排/ })).toHaveAttribute('href', '/career-calendar?view=actions');
});

it('makes every pending confirmation reachable without searching general history', async () => {
  vi.mocked(listPendingConfirmations).mockResolvedValue(Array.from({ length: 4 }, (_, i) => ({ conversation_id: `conversation-${i}`, turn_status: 'waiting', interaction: { id: `interaction-${i}`, kind: 'approval' } })) as PendingConfirmation[]);
  show();
  fireEvent.click(await screen.findByRole('button', { name: '查看其余协作' }));
  expect(screen.getAllByRole('link', { name: /确认操作/ })).toHaveLength(4);
  expect(screen.getAllByRole('link', { name: /确认操作/ })[3]).toHaveAttribute('href', '/general-chat?session=conversation-3');
});
