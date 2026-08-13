import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GmailObservation, GmailObservationReviewCard } from '@/types/gmailObservation';
import type { PersistentTask } from '@/types/persistentTask';

const api = vi.hoisted(() => ({
  listGmailObservations: vi.fn(),
  listGmailReviewCards: vi.fn(),
  syncGmailObservations: vi.fn(),
  rebaselineGmailObservations: vi.fn(),
  resolveGmailReviewCard: vi.fn(),
  retractGmailObservation: vi.fn(),
}));
vi.mock('@/api/gmailObservations', () => api);
vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn().mockResolvedValue([]) }));

import { GmailObservationCards } from './GmailObservationCards';

const task: PersistentTask = {
  id: 'pt-1', user_id: 1, conversation_id: 'conversation-1', title: 'Gmail 求职事件',
  instruction: '处理新的求职邮件', state: 'active', version: 1,
  trigger_kind: 'event', trigger_spec_json: { kind: 'event', connector: 'gmail', event_types: ['message_added'] },
  read_scope_json: ['gmail:job_observations'], action_scope_json: [],
  allowed_tool_names_json: ['read_career_context', 'read_gmail_observations', 'review_gmail_observation'],
  skill_refs_json: [],
  user_request_identity: 'message:create', user_request_version: null,
  compensation_blocked_at: null, next_due_at: null,
  created_at: '2026-08-13T08:00:00Z', updated_at: '2026-08-13T08:00:00Z',
};

const snapshot = {
  id: 'snapshot-1', observation_id: 'observation-1', snapshot_version: '101:v1',
  provider_history_id: '101', provider_message_id: 'msg-1', provider_thread_id: 'thread-1',
  content_available: true,
  received_at: '2026-08-13T08:00:00Z', from_hint: 'recruiter@example.com',
  subject: 'Interview invitation', snippet: 'Please choose a time.', content_sha256: 'a'.repeat(64),
  observed_at: '2026-08-13T08:00:01Z', created_at: '2026-08-13T08:00:01Z',
};

const card: GmailObservationReviewCard = {
  id: 'card-1', persistent_task_id: task.id, observation_id: 'observation-1',
  source_snapshot_id: snapshot.id, status: 'pending', version: 1,
  candidate_event_kind: 'interview_scheduled', candidate_opportunity_id: null,
  occurred_at: '2026-08-13T08:00:00Z', description: '招聘方邀请面试', step_summary: null,
  confidence: 0.81, unique_match: false, rationale: '公司相同，但岗位无法唯一匹配。',
  new_opportunity_json: {
    company_name: 'Example', job_title: 'Engineer', application_provider: 'greenhouse',
    external_application_id: 'app-1',
  },
  process_event_id: null, resolution_note: null, resolved_at: null,
  created_at: '2026-08-13T08:00:02Z', updated_at: '2026-08-13T08:00:02Z',
  source_snapshot: snapshot,
};

const appliedObservation: GmailObservation = {
  id: 'observation-1', gmail_account_id: 'gmail-1', provider_message_id: 'msg-1',
  provider_thread_id: 'thread-1', received_at: snapshot.received_at,
  observed_at: snapshot.observed_at, status: 'applied', version: 2,
  candidate_event_kind: 'interview_scheduled', classification_confidence: 0.99,
  unique_match: true, analysis_summary: '唯一申请号匹配', matched_job_opportunity_id: 'job-1',
  applied_process_event_id: 'event-1', retraction_process_event_id: null,
  notification_summary: '已自动记录；可以撤销。',
  created_at: snapshot.created_at, updated_at: snapshot.created_at, latest_snapshot: snapshot,
};

function renderCards() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <GmailObservationCards task={task} observationIds={['observation-1']} />
    </QueryClientProvider>,
  );
}

describe('GmailObservationCards', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.listGmailReviewCards.mockResolvedValue([card]);
    api.listGmailObservations.mockResolvedValue([]);
    api.resolveGmailReviewCard.mockResolvedValue({
      outcome: 'applied', observation: appliedObservation, review_card: { ...card, status: 'approved' },
      process_event_id: 'event-1',
    });
  });

  it('keeps ambiguous email state in a review card until the user approves', async () => {
    renderCards();
    expect(await screen.findByText('Interview invitation')).toBeInTheDocument();
    expect(screen.getByText('公司相同，但岗位无法唯一匹配。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '批准并记录' }));
    await waitFor(() => expect(api.resolveGmailReviewCard).toHaveBeenCalledWith(expect.objectContaining({
      taskId: task.id,
      card,
      decision: 'approve',
      eventKind: 'interview_scheduled',
    })));
  });

  it('shows an explicit append-only retraction path for automatic applications', async () => {
    api.listGmailReviewCards.mockResolvedValue([]);
    api.listGmailObservations.mockResolvedValue([appliedObservation]);
    api.retractGmailObservation.mockResolvedValue({ ...appliedObservation, status: 'retracted' });
    renderCards();
    expect(await screen.findByText('已自动记录；可以撤销。')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '撤销记录' }));
    fireEvent.click(screen.getByRole('button', { name: '追加撤销事件' }));
    await waitFor(() => expect(api.retractGmailObservation).toHaveBeenCalledWith(
      appliedObservation,
      expect.stringContaining('撤销自动记录'),
      expect.any(String),
    ));
  });

  it('offers explicit rebaseline only after Gmail reports an expired cursor', async () => {
    api.listGmailReviewCards.mockResolvedValue([]);
    api.syncGmailObservations.mockRejectedValue({
      response: { data: { detail: 'history_cursor_expired' } },
    });
    api.rebaselineGmailObservations.mockResolvedValue({
      initialized_cursor: true,
      cursor_after: '200',
      observations_created: 0,
      snapshots_created: 0,
      triggers_created: 0,
      turns_admitted: 0,
      turn_ids: [],
    });
    renderCards();

    expect(screen.queryByRole('button', { name: '从当前时点重建游标' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '立即增量同步' }));
    const rebaseline = await screen.findByRole('button', { name: '从当前时点重建游标' });
    fireEvent.click(rebaseline);
    await waitFor(() => expect(api.rebaselineGmailObservations).toHaveBeenCalledWith(expect.any(String)));
  });
});
