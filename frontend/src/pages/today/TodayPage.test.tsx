import { listCareerActivity } from '@/api/careerActivity';
vi.mock('@/api/careerActivity', () => ({ listCareerActivity: vi.fn(() => Promise.resolve([])) }));
import { factInteraction } from '@/test/invitationFixtures';
import { listPendingConfirmations } from '@/api/interviewInvitations';
vi.mock('@/api/interviewInvitations', () => ({ listPendingConfirmations: vi.fn() }));
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getNextActionAgenda } from '@/api/careerInsights';
import { listJobOpportunities } from '@/api/careerProcess';
import type { NextAction, NextActionAgendaItem } from '@/types/career';
import { TodayPage } from './TodayPage';
import { getWorkspaceOverview } from '@/api/workspace';
vi.mock('@/api/workspace', () => ({ getWorkspaceOverview: vi.fn() }));

vi.mock('@/api/careerInsights', () => ({ getNextActionAgenda: vi.fn() }));
vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn() }));

function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><TodayPage /></MemoryRouter>
  </QueryClientProvider>);
}

function item(status: 'planned' | 'suggested', content: string): NextActionAgendaItem {
  const action: NextAction = {
    id: content, user_id: 1, content, status, version: 1, time_kind: 'deadline',
    job_opportunity_id: null, interview_record_id: null, offer_id: null, artifact_id: null,
    starts_at: null, ends_at: null, due_at: '2026-09-14T08:00:00Z', original_time_text: null,
    source_timezone: 'Asia/Shanghai', source_kind: 'user_request', source_identity: 'test', source_version: null,
    planned_at: null, resolved_at: null, close_reason: null, reminder_at: null, reminder_next_attempt_at: null,
    reminder_channel: null, reminder_delivered_at: null, reminder_dismissed_at: null,
    created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  };
  return { action, bucket: status === 'suggested' ? 'suggested' : 'today', overdue: true, due_soon: false, conflict_action_ids: [], duplicate_action_ids: [] };
}

describe('TodayPage', () => {
  beforeEach(() => {
    vi.mocked(listPendingConfirmations).mockResolvedValue([]);
    vi.mocked(getWorkspaceOverview).mockResolvedValue({ has_resume: false, active_opportunities: 0, open_actions: 0, recent_work: [] });
    vi.mocked(getNextActionAgenda).mockResolvedValue({ generated_at: '', items: [] });
    vi.mocked(listJobOpportunities).mockResolvedValue([]);
  });
  it('shows connection failure instead of pretending the user has no tasks', async () => {
    vi.mocked(getNextActionAgenda).mockRejectedValue(new Error('offline'));
    mount();
    expect(await screen.findByText('暂时无法读取安排')).toBeInTheDocument();
    expect(screen.queryByText('眼下没有需要处理的安排')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: '需要处理' })).toHaveTextContent('需要处理');
    expect(screen.getByRole('button', { name: '需要处理' })).not.toHaveTextContent('0');
  });
  it('distinguishes confirmed empty state and provides a working next step', async () => {
    mount();
    expect(await screen.findByText('你现在最想解决什么？')).toBeInTheDocument();
    expect(screen.queryByText('眼下没有需要处理的安排')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /一起改好我的简历/ })).toHaveAttribute('href', '/general-chat?start=resume');
  });
  it('keeps an overdue suggestion out of the confirmed agenda and carries its identity into Copilot', async () => {
    vi.mocked(getNextActionAgenda).mockResolvedValue({ generated_at: '', items: [item('planned', '准备技术面试'), item('suggested', '建议修改简历')] });
    mount();
    expect(await screen.findByText('准备技术面试')).toBeInTheDocument();
    expect(screen.queryByText('建议修改简历')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /待采纳建议/ }));
    expect(screen.getByText('建议修改简历')).toBeInTheDocument();
    expect(screen.getByText(/尚未加入计划/)).toBeInTheDocument();
    const href = screen.getByRole('link', { name: /与 Copilot 讨论/ }).getAttribute('href')!;
    expect(new URL(href, 'http://localhost').searchParams.get('object_id')).toBe('建议修改简历');
  });
});

it('projects an actual pending fact decision without applying it on load', async () => {
  vi.mocked(getWorkspaceOverview).mockResolvedValue({ has_resume: false, active_opportunities: 0, open_actions: 0, recent_work: [] });
  vi.mocked(getNextActionAgenda).mockResolvedValue({ generated_at: '', items: [] });
  vi.mocked(listJobOpportunities).mockResolvedValue([]);
  vi.mocked(listPendingConfirmations).mockResolvedValue([{ conversation_id: 'session-1', turn_status: 'waiting', interaction: factInteraction }]);
  mount(); expect(await screen.findByRole('button', { name: '确认这些事实' })).toBeDisabled();
  expect(screen.getByText('测试公司')).toBeInTheDocument();
});

it('shows canonical domain and harness activity instead of fabricated feed entries', async () => {
  vi.mocked(listPendingConfirmations).mockResolvedValue([]);
  vi.mocked(listCareerActivity).mockResolvedValue([{ event_id: 'event-1', event_kind: 'confirmed', event_category: 'domain',
    schema_version: 1, occurred_at: '2026-09-18T00:00:00Z', operation_id: 'op-1', conversation_id: null, interaction_id: null,
    replayable: true, payload: { title: '真实测试邀请已确认', status: 'verified' } }]);
  mount(); expect(await screen.findByText('真实测试邀请已确认')).toBeInTheDocument();
  expect(screen.getByText('业务事实 · verified')).toBeInTheDocument();
});
